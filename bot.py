import discord
from discord.ext import commands
from discord import option # Required for slash command options
import os
from dotenv import load_dotenv
from mcipc.rcon import Client as AsyncRCONClient # Use the async version
import asyncio
import logging

# --- Constants ---
BLACKLIST_FILE = "blacklist.txt"

# --- Setup Logging ---
# Configure logging for better debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord') # Get the discord logger

# --- Load Environment Variables ---
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RCON_HOST = os.getenv("RCON_HOST")
# Ensure RCON_PORT is an integer
try:
    RCON_PORT = int(os.getenv("RCON_PORT"))
except (TypeError, ValueError):
    logger.error("RCON_PORT is not a valid integer in the .env file. Please check.")
    exit() # Exit if the port isn't valid
RCON_PASSWORD = os.getenv("RCON_PASSWORD")

# Basic validation for environment variables
if not all([DISCORD_BOT_TOKEN, RCON_HOST, RCON_PORT, RCON_PASSWORD]):
    logger.error("One or more environment variables (DISCORD_BOT_TOKEN, RCON_HOST, RCON_PORT, RCON_PASSWORD) are missing in the .env file.")
    exit() # Exit if any variable is missing

# --- Bot Initialization ---
# Define necessary intents. Default intents are usually fine for slash commands,
# but let's be explicit. No special intents needed for this core functionality yet.
intents = discord.Intents.default()
# If you needed message content later, you'd add: intents.message_content = True

bot = discord.Bot(intents=intents)

# --- Blacklist Management ---
# In-memory cache of the blacklist
blacklist = set()

def load_blacklist():
    """Loads the blacklist from the file into the in-memory set."""
    global blacklist
    try:
        # Create the file if it doesn't exist
        if not os.path.exists(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
                f.write("# Blacklisted command segments (one per line)\n")
            logger.info(f"'{BLACKLIST_FILE}' not found, created an empty one.")
            blacklist = set() # Ensure blacklist is empty if file was just created
            return

        # Read the file
        with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
            # Read lines, strip whitespace, ignore empty lines and comments
            blacklist = {line.strip().lower() for line in f if line.strip() and not line.startswith('#')}
        logger.info(f"Loaded {len(blacklist)} segments from {BLACKLIST_FILE}")
    except Exception as e:
        logger.error(f"Error loading blacklist from {BLACKLIST_FILE}: {e}")
        blacklist = set() # Reset blacklist on error to prevent issues

def save_blacklist():
    """Saves the in-memory blacklist set back to the file."""
    try:
        with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
            f.write("# Blacklisted command segments (one per line)\n")
            # Sort the blacklist for consistency before writing
            for segment in sorted(list(blacklist)):
                f.write(f"{segment}\n")
        logger.info(f"Saved {len(blacklist)} segments to {BLACKLIST_FILE}")
    except Exception as e:
        logger.error(f"Error saving blacklist to {BLACKLIST_FILE}: {e}")

# --- Helper Function for Embeds ---
def create_embed(title: str, description: str, color: discord.Color = discord.Color.blue()) -> discord.Embed:
    """Creates a standard Discord embed."""
    embed = discord.Embed(title=title, description=description, color=color)
    # You can add footers, timestamps, etc. here if needed later
    # embed.set_footer(text="My Bot Name")
    # embed.timestamp = discord.utils.utcnow()
    return embed

# --- Event Handlers ---
@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    load_blacklist() # Load the blacklist on startup
    logger.info(f'Logged in as {bot.user.name} ({bot.user.id})')
    logger.info('------')
    print(f'Bot {bot.user.name} is ready.') # Also print to console

# --- Slash Commands ---

# Group for blacklist commands
blacklist_group = bot.create_group("blacklist", "Manage the command blacklist")

@blacklist_group.command(description="Adds a segment to the command blacklist.")
@commands.has_permissions(administrator=True) # Only administrators can use this
@option("segment", description="The text segment to blacklist (case-insensitive)", required=True)
async def add(ctx: discord.ApplicationContext, segment: str):
    """Adds a string segment to the blacklist."""
    global blacklist
    segment_lower = segment.strip().lower()

    if not segment_lower:
        embed = create_embed("Blacklist Error", "Blacklist segment cannot be empty.", discord.Color.red())
        await ctx.respond(embed=embed, ephemeral=True)
        return

    if segment_lower in blacklist:
        embed = create_embed("Blacklist Info", f"Segment `{segment}` is already in the blacklist.", discord.Color.orange())
        await ctx.respond(embed=embed, ephemeral=True)
    else:
        blacklist.add(segment_lower)
        save_blacklist() # Persist changes
        logger.info(f"Admin '{ctx.author.name}' added '{segment_lower}' to blacklist.")
        embed = create_embed("Blacklist Success", f"Segment `{segment}` added to the blacklist.", discord.Color.green())
        await ctx.respond(embed=embed, ephemeral=True)

@blacklist_group.command(description="Removes a segment from the command blacklist.")
@commands.has_permissions(administrator=True) # Only administrators can use this
@option("segment", description="The text segment to remove from the blacklist (case-insensitive)", required=True)
async def remove(ctx: discord.ApplicationContext, segment: str):
    """Removes a string segment from the blacklist."""
    global blacklist
    segment_lower = segment.strip().lower()

    if not segment_lower:
        embed = create_embed("Blacklist Error", "Segment cannot be empty.", discord.Color.red())
        await ctx.respond(embed=embed, ephemeral=True)
        return

    if segment_lower in blacklist:
        blacklist.remove(segment_lower)
        save_blacklist() # Persist changes
        logger.info(f"Admin '{ctx.author.name}' removed '{segment_lower}' from blacklist.")
        embed = create_embed("Blacklist Success", f"Segment `{segment}` removed from the blacklist.", discord.Color.green())
        await ctx.respond(embed=embed, ephemeral=True)
    else:
        embed = create_embed("Blacklist Info", f"Segment `{segment}` not found in the blacklist.", discord.Color.orange())
        await ctx.respond(embed=embed, ephemeral=True)

@blacklist_group.command(description="Lists all segments currently in the command blacklist.")
@commands.has_permissions(administrator=True) # Only administrators can use this
async def list(ctx: discord.ApplicationContext):
    """Lists all blacklisted string segments."""
    global blacklist
    if not blacklist:
        description = "The blacklist is currently empty."
    else:
        # Format the list nicely, perhaps using bullet points or numbers
        formatted_list = "\n".join(f"- `{segment}`" for segment in sorted(list(blacklist)))
        description = f"**Current Blacklisted Segments:**\n{formatted_list}"

    embed = create_embed("Command Blacklist", description, discord.Color.purple())
    await ctx.respond(embed=embed, ephemeral=True) # Ephemeral so only the admin sees it

@bot.slash_command(description="Sends a command to the Minecraft server via RCON.")
@option("command_string", description="The command to send to the server (omit leading '/')", required=True)
async def command(ctx: discord.ApplicationContext, command_string: str):
    """Handles the /command slash command, removing leading '/' before sending."""

    # --- Command Preprocessing ---
    # Keep the original string as typed by the user for display/logging
    original_command_string = command_string
    # Prepare a version for blacklist check (lowercase, potentially without slash)
    # We might want to blacklist based on the command regardless of the slash
    command_for_blacklist_check = command_string.lstrip('/').lower()

    # Check against blacklist
    for blocked_segment in blacklist:
        if blocked_segment and blocked_segment in command_for_blacklist_check:
            # Log using the original string the user typed
            logger.warning(f"User '{ctx.author.name}' tried to run blacklisted command: '{original_command_string}' (matched: '{blocked_segment}')")
            await ctx.respond("Naughty Naughty, that command is in the blacklist", ephemeral=True)
            return

    # Proceed with RCON connection and command execution
    await ctx.defer(ephemeral=True)

    success = False
    response = None
    try:
        # Log the original command string as typed by the user
        logger.info(f"User '{ctx.author.name}' attempting RCON command: '{original_command_string}'")

        # --- RCON Execution (Synchronous code in separate thread) ---
        def rcon_sync_operation():
            # Remove leading slash right before sending to RCON
            command_to_send = original_command_string.lstrip('/')
            logger.debug(f"Stripped leading '/': Sending '{command_to_send}' to RCON.")

            rcon_client = AsyncRCONClient(RCON_HOST, RCON_PORT, passwd=RCON_PASSWORD)
            with rcon_client:
                return rcon_client.run(command_to_send)

        response = await asyncio.to_thread(rcon_sync_operation)
        # --- End RCON Execution ---

        # Log the response using the original command string for context
        logger.info(f"RCON command '{original_command_string}' sent successfully. Response: {response}")

        # Respond with the server's response (if any) using an ephemeral embed
        if response and response.strip():
            max_len = 4000
            response_formatted = f"```\n{response[:max_len]}{'...' if len(response) > max_len else ''}\n```"
            embed_title = "Command Executed"
            # Show the original command string in the embed
            embed_desc = f"**Command:** `{original_command_string}`\n**Server Response:**\n{response_formatted}"
            embed_color = discord.Color.green()
        else:
            embed_title = "Command Sent"
            # Show the original command string in the embed
            embed_desc = f"Command `{original_command_string}` sent successfully. No response from server."
            embed_color = discord.Color.blue()

        embed = create_embed(embed_title, embed_desc, embed_color)
        await ctx.followup.send(embed=embed, ephemeral=True)
        success = True

    # Handle potential exceptions...
    except ConnectionRefusedError:
        logger.error(f"RCON connection refused for {RCON_HOST}:{RCON_PORT}. Is the server running and RCON enabled?")
        embed = create_embed("RCON Error", "Could not connect to the Minecraft server (Connection Refused). Please check server status and RCON configuration.", discord.Color.red())
        await ctx.followup.send(embed=embed, ephemeral=True)
    except TimeoutError:
        logger.error(f"RCON connection timed out for {RCON_HOST}:{RCON_PORT}.")
        embed = create_embed("RCON Error", "Connection to the Minecraft server timed out.", discord.Color.red())
        await ctx.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        logger.exception(f"An unexpected error occurred during RCON command execution: {e}")
        embed = create_embed("Unexpected Error", f"An error occurred while sending the command: `{type(e).__name__}`. Please check the bot logs.", discord.Color.dark_red())
        await ctx.followup.send(embed=embed, ephemeral=True)

    # Send public confirmation message ONLY if RCON succeeded AND response doesn't contain 'unknown'
    if success and response is not None and "unknown" not in response.lower():
        try:
            max_public_len = 1900
            truncated_response = response[:max_public_len] + ('...' if len(response) > max_public_len else '')
            await ctx.channel.send(f"{ctx.author.mention} {truncated_response}")
        except Exception as e:
            logger.error(f"Failed to send public confirmation message after successful command: {e}")

# --- Error Handling for Commands ---
@bot.event
async def on_application_command_error(ctx: discord.ApplicationContext, error: discord.DiscordException):
    """Handles errors globally for application commands."""
    if isinstance(error, commands.MissingPermissions):
        embed = create_embed("Permission Denied", "You do not have the required permissions to use this command.", discord.Color.orange())
        # Check if interaction is deferred before responding
        if ctx.interaction.response.is_done():
             await ctx.followup.send(embed=embed, ephemeral=True)
        else:
             await ctx.respond(embed=embed, ephemeral=True)
    # Add more specific error handling as needed
    # elif isinstance(error, commands.CommandNotFound): # Less likely with slash commands
    #     embed = create_embed("Error", "Sorry, I don't recognize that command.", discord.Color.red())
    #     await ctx.respond(embed=embed, ephemeral=True)
    else:
        logger.error(f"Unhandled application command error in '{ctx.command.qualified_name if ctx.command else 'unknown command'}': {error}")
        embed = create_embed("Unexpected Error", "An unexpected error occurred. Please contact the bot administrator.", discord.Color.dark_red())
        if ctx.interaction.response.is_done():
            await ctx.followup.send(embed=embed, ephemeral=True)
        else:
            await ctx.respond(embed=embed, ephemeral=True)
        # Optionally, re-raise the error if you want it to propagate further for top-level logging
        # raise error

# --- Run the Bot ---
if __name__ == "__main__":
    if DISCORD_BOT_TOKEN:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        logger.critical("DISCORD_BOT_TOKEN is not set. Bot cannot start.") 