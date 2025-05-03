import discord
from discord.ext import commands
from discord import option # Required for slash command options
import os
from dotenv import load_dotenv
from mcipc.rcon import Client as AsyncRCONClient # Use the async version
import asyncio
import logging
import sqlite3
from contextlib import contextmanager
import random
import time
import json

# --- Constants ---
DATABASE_FILE = "blacklist.db"
MIN_COOLDOWN = 15  # Minimum cooldown in seconds
MAX_COOLDOWN = 45  # Maximum cooldown in seconds

# Colors for in-game titles
ROYAL_BLUE = "#305CDE"
SLATE_GREY = "#cfeafa"

# Command validation
INVALID_COMMAND_INDICATORS = [
    "can't find",
    "expected",
    "too far away",
    "unknown",
    "incorrect",
    "could not",
    "malformed",
    "too many",
    "no entity was found"
]

def create_title_command(username: str, response: str) -> tuple[str, str]:
    """
    Creates a formatted title command for Minecraft.
    Args:
        username: Discord username
        response: Server response message
    Returns:
        Formatted title command string
    """
    # Create the JSON components for the title
    title_components = [
        {"text": username, "color": ROYAL_BLUE.replace("#", "#")},
    ]
    
    # Convert to JSON string and escape quotes
    title_json = json.dumps(title_components)

    # Create the JSON components for the subtitle
    subtitle_components = [
        {"text": response, "color": SLATE_GREY.replace("#", "#")}
    ]

    # Convert to JSON string and escape quotes
    subtitle_json = json.dumps(subtitle_components)

    # Assemble the title and subtitle commands
    title_cmd = f'title @a title {title_json}'
    subtitle_cmd = f'title @a subtitle {subtitle_json}'

    # Create the complete title command
    logger.info(title_cmd)
    logger.info(subtitle_cmd)
    return title_cmd, subtitle_cmd

def is_command_valid(response: str) -> bool:
    """Check if a command response indicates success."""
    if not response:
        return False
    response_lower = response.lower()
    return not any(indicator in response_lower for indicator in INVALID_COMMAND_INDICATORS)

def send_title_notification_sync(rcon_client, username: str, response: str):
    """
    Synchronously sends a title notification to all players on the server.
    Args:
        rcon_client: Active RCON client
        username: Discord username
        response: Server response message
    """
    try:
        title_cmd, subtitle_cmd = create_title_command(username, response)
        rcon_client.run("playsound minecraft:block.beacon.activate voice @a ~ ~ ~ 1000 1")
        rcon_client.run(subtitle_cmd)
        rcon_client.run(title_cmd)
    except Exception as e:
        logger.error(f"Failed to send title notification: {e}")

# --- Cooldown Management ---
class CooldownManager:
    def __init__(self):
        self.is_cooling_down = False
        self.cooldown_end_time = 0
        self.current_cooldown = 0
        self._task = None
        self._last_channel = None  # Store the last channel for notifications

    def start_cooldown(self, channel):
        """Start a new random cooldown timer."""
        self.current_cooldown = random.randint(MIN_COOLDOWN, MAX_COOLDOWN)
        self.is_cooling_down = True
        self.cooldown_end_time = time.time() + self.current_cooldown
        self._last_channel = channel
        # Cancel existing task if any
        if self._task and not self._task.done():
            self._task.cancel()
        
    async def _cooldown_timer(self):
        """Async task to handle cooldown timer and notifications."""
        try:
            await asyncio.sleep(self.current_cooldown)
            self.is_cooling_down = False
            if self._last_channel:
                await self._last_channel.send("🔄 Cooldown timer reset! The bot is ready to accept new commands.")
        except asyncio.CancelledError:
            pass

    def start_timer_task(self):
        """Start the async timer task."""
        self._task = asyncio.create_task(self._cooldown_timer())

    def get_remaining_time(self):
        """Get remaining cooldown time in seconds."""
        if not self.is_cooling_down:
            return 0
        remaining = self.cooldown_end_time - time.time()
        return max(0, round(remaining))

# Create global cooldown manager instance
cooldown_mgr = CooldownManager()

# --- Setup Logging ---
# Configure logging for better debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord') # Get the discord logger

# --- Database Setup ---
def init_database():
    """Initialize the SQLite database and create the blacklist table if it doesn't exist."""
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blacklist (
                    segment TEXT PRIMARY KEY,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        logger.info(f"Database initialized successfully at {DATABASE_FILE}")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        yield conn
    finally:
        conn.close()

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
        if not os.path.exists(DATABASE_FILE):
            init_database()
            blacklist = set() # Ensure blacklist is empty if file was just created
            return

        # Read the file
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT segment FROM blacklist")
            rows = cursor.fetchall()
            blacklist = {row[0] for row in rows}
        logger.info(f"Loaded {len(blacklist)} segments from {DATABASE_FILE}")
    except Exception as e:
        logger.error(f"Error loading blacklist from {DATABASE_FILE}: {e}")
        blacklist = set() # Reset blacklist on error to prevent issues

def save_blacklist():
    """Saves the in-memory blacklist set back to the file."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM blacklist")
            for segment in blacklist:
                cursor.execute("INSERT INTO blacklist (segment) VALUES (?)", (segment,))
            conn.commit()
        logger.info(f"Saved {len(blacklist)} segments to {DATABASE_FILE}")
    except Exception as e:
        logger.error(f"Error saving blacklist to {DATABASE_FILE}: {e}")

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
    try:
        init_database()  # Initialize the database on startup
        logger.info(f'Logged in as {bot.user.name} ({bot.user.id})')
        logger.info('------')
        print(f'Bot {bot.user.name} is ready.')
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        await bot.close()  # Shutdown the bot if database initialization fails

# --- Slash Commands ---

# Group for blacklist commands
blacklist_group = bot.create_group("blacklist", "Manage the command blacklist")

@blacklist_group.command(description="Adds a segment to the command blacklist.")
@commands.has_permissions(administrator=True) # Only administrators can use this
@option("segment", description="The text segment to blacklist (case-insensitive)", required=True)
async def add(ctx: discord.ApplicationContext, segment: str):
    """Adds a string segment to the blacklist."""
    segment_lower = segment.strip().lower()

    if not segment_lower:
        embed = create_embed("Blacklist Error", "Blacklist segment cannot be empty.", discord.Color.red())
        await ctx.respond(embed=embed, ephemeral=True)
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Check if segment already exists
            cursor.execute("SELECT 1 FROM blacklist WHERE segment = ?", (segment_lower,))
            if cursor.fetchone():
                embed = create_embed("Blacklist Info", f"Segment `{segment}` is already in the blacklist.", discord.Color.orange())
                await ctx.respond(embed=embed, ephemeral=True)
                return

            # Add new segment
            cursor.execute("INSERT INTO blacklist (segment) VALUES (?)", (segment_lower,))
            conn.commit()
            logger.info(f"Admin '{ctx.author.name}' added '{segment_lower}' to blacklist.")
            embed = create_embed("Blacklist Success", f"Segment `{segment}` added to the blacklist.", discord.Color.green())
            await ctx.respond(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"Error adding to blacklist: {e}")
        embed = create_embed("Database Error", "Failed to add segment to blacklist.", discord.Color.red())
        await ctx.respond(embed=embed, ephemeral=True)

@blacklist_group.command(description="Removes a segment from the command blacklist.")
@commands.has_permissions(administrator=True) # Only administrators can use this
@option("segment", description="The text segment to remove from the blacklist (case-insensitive)", required=True)
async def remove(ctx: discord.ApplicationContext, segment: str):
    """Removes a string segment from the blacklist."""
    segment_lower = segment.strip().lower()

    if not segment_lower:
        embed = create_embed("Blacklist Error", "Segment cannot be empty.", discord.Color.red())
        await ctx.respond(embed=embed, ephemeral=True)
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM blacklist WHERE segment = ?", (segment_lower,))
            if cursor.rowcount > 0:
                conn.commit()
                logger.info(f"Admin '{ctx.author.name}' removed '{segment_lower}' from blacklist.")
                embed = create_embed("Blacklist Success", f"Segment `{segment}` removed from the blacklist.", discord.Color.green())
            else:
                embed = create_embed("Blacklist Info", f"Segment `{segment}` not found in the blacklist.", discord.Color.orange())
            await ctx.respond(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"Error removing from blacklist: {e}")
        embed = create_embed("Database Error", "Failed to remove segment from blacklist.", discord.Color.red())
        await ctx.respond(embed=embed, ephemeral=True)

@blacklist_group.command(description="Lists all segments currently in the command blacklist.")
@commands.has_permissions(administrator=True) # Only administrators can use this
async def list(ctx: discord.ApplicationContext):
    """Lists all blacklisted string segments."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT segment FROM blacklist ORDER BY segment")
            segments = cursor.fetchall()

            if not segments:
                description = "The blacklist is currently empty."
            else:
                # Format the list nicely with bullet points
                formatted_list = "\n".join(f"- `{segment[0]}`" for segment in segments)
                description = f"**Current Blacklisted Segments:**\n{formatted_list}"

            embed = create_embed("Command Blacklist", description, discord.Color.purple())
            await ctx.respond(embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"Error listing blacklist: {e}")
        embed = create_embed("Database Error", "Failed to retrieve blacklist.", discord.Color.red())
        await ctx.respond(embed=embed, ephemeral=True)

# Update the command check to use direct database query
async def is_command_blacklisted(command_string: str) -> bool:
    """Checks if a command contains any blacklisted segments."""
    command_lower = command_string.lower()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT segment FROM blacklist")
            blacklisted_segments = cursor.fetchall()
            return any(segment[0] in command_lower for segment in blacklisted_segments)
    except Exception as e:
        logger.error(f"Error checking blacklist: {e}")
        return False  # Fail open if database error

@bot.slash_command(description="Sends a command to the Minecraft server via RCON.")
@option("command_string", description="The command to send to the server (omit leading '/')", required=True)
async def command(ctx: discord.ApplicationContext, command_string: str):
    """Handles the /command slash command, removing leading '/' before sending."""
    # Check cooldown first
    if cooldown_mgr.is_cooling_down:
        remaining_time = cooldown_mgr.get_remaining_time()
        embed = create_embed(
            "Command Cooldown",
            f"Please wait {remaining_time} seconds before sending another command.",
            discord.Color.orange()
        )
        await ctx.respond(embed=embed, ephemeral=True)
        return

    # Keep the original string as typed by the user for display/logging
    original_command_string = command_string
    # Prepare a version for blacklist check (lowercase, potentially without slash)
    command_for_blacklist_check = command_string.lstrip('/').lower()

    # Check against blacklist
    if await is_command_blacklisted(command_for_blacklist_check):
        logger.warning(f"User '{ctx.author.name}' tried to run blacklisted command: '{original_command_string}'")
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
                response = rcon_client.run(command_to_send)
                
                # If command was successful, send the title notification
                if is_command_valid(response):
                    # Use the raw server response
                    display_response = response.strip()
                    
                    # Send title notification synchronously since we're already in a sync context
                    send_title_notification_sync(rcon_client, ctx.author.name, display_response)
                
                return response

        response = await asyncio.to_thread(rcon_sync_operation)
        # --- End RCON Execution ---

        # Log the response using the original command string for context
        logger.info(f"RCON command '{original_command_string}' sent successfully. Response: {response}")

        # Check if command was invalid
        if not is_command_valid(response):
            embed = create_embed(
                "Invalid Command",
                f"**Command:** `{original_command_string}`\n**Error:** {response}",
                discord.Color.orange()
            )
            await ctx.followup.send(embed=embed, ephemeral=True)
            return

        # Command was successful, start cooldown
        cooldown_mgr.start_cooldown(ctx.channel)
        cooldown_mgr.start_timer_task()

        # Respond with the server's response (if any) using an ephemeral embed
        if response and response.strip():
            max_len = 4000
            response_formatted = f"```\n{response[:max_len]}{'...' if len(response) > max_len else ''}\n```"
            embed_title = "Command Executed"
            # Show the original command string in the embed
            embed_desc = f"**Command:** `{original_command_string}`\n**Server Response:**\n{response_formatted}\n\n⏳ Command cooldown started ({cooldown_mgr.current_cooldown} seconds)"
            embed_color = discord.Color.green()
        else:
            embed_title = "Command Sent"
            # Show the original command string in the embed
            embed_desc = f"Command `{original_command_string}` sent successfully. No response from server.\n\n⏳ Command cooldown started ({cooldown_mgr.current_cooldown} seconds)"
            embed_color = discord.Color.blue()

        embed = create_embed(embed_title, embed_desc, embed_color)
        await ctx.followup.send(embed=embed, ephemeral=True)
        success = True

        # Send public message about command execution and cooldown
        await ctx.channel.send(f"🎮 {ctx.author.mention} executed a command. ⏳ Cooldown timer started ({cooldown_mgr.current_cooldown} seconds)")

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
