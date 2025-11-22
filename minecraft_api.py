import aiohttp
import asyncio
import re
from typing import Optional, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class MinecraftApiService:
    """Service for interacting with Mojang's Minecraft API"""
    
    API_ENDPOINT = 'https://api.mojang.com/users/profiles/minecraft'
    MAX_RETRIES = 3
    INITIAL_RETRY_DELAY = 2000  # milliseconds
    MAX_CONCURRENT_REQUESTS = 5
    
    active_requests = 0
    request_queue: List[asyncio.Task] = []
    
    @staticmethod
    def is_valid_minecraft_username(username: str) -> bool:
        """
        Validates a Minecraft username according to official rules:
        1. Only alphanumeric characters and underscore
        2. Length between 3 and 16 characters
        3. No consecutive underscores
        4. No underscore at start or end
        5. Must start with a letter
        """
        if not username or len(username) < 3 or len(username) > 16:
            return False
        
        # Must start with a letter
        if not username[0].isalpha():
            return False
        
        # Must end with alphanumeric (not underscore)
        if not username[-1].isalnum():
            return False
        
        # Only alphanumeric and underscore
        if not re.match(r'^[a-z][a-z0-9_]*[a-z0-9]$', username, re.IGNORECASE):
            return False
        
        return True
    
    @staticmethod
    async def delay(ms: int) -> None:
        """Delay execution for specified milliseconds"""
        await asyncio.sleep(ms / 1000.0)
    
    @staticmethod
    async def execute_with_rate_limit(operation):
        """Execute operation with concurrent request rate limiting"""
        while MinecraftApiService.active_requests >= MinecraftApiService.MAX_CONCURRENT_REQUESTS:
            await MinecraftApiService.delay(100)
        
        MinecraftApiService.active_requests += 1
        try:
            return await operation()
        finally:
            MinecraftApiService.active_requests -= 1
            if MinecraftApiService.request_queue:
                next_request = MinecraftApiService.request_queue.pop(0)
                try:
                    next_request.set_result(None)
                except:
                    pass
    
    @staticmethod
    async def retry_operation(operation, retry_count: int = 0):
        """Retry operation with exponential backoff for rate limits"""
        try:
            return await MinecraftApiService.execute_with_rate_limit(operation)
        except aiohttp.ClientError as error:
            if error.status == 429 and retry_count < MinecraftApiService.MAX_RETRIES:
                logger.error(f"Rate limit hit: {error.status} - {error}")
                delay_ms = MinecraftApiService.INITIAL_RETRY_DELAY * (2 ** retry_count)
                logger.info(f"Rate limited, retrying in {delay_ms}ms... (Attempt {retry_count + 1}/{MinecraftApiService.MAX_RETRIES})")
                await MinecraftApiService.delay(delay_ms)
                return await MinecraftApiService.retry_operation(operation, retry_count + 1)
            elif isinstance(error, asyncio.TimeoutError):
                logger.error(f"Connection timeout: {error}")
                raise Exception('API connection timeout')
            raise error
        except asyncio.TimeoutError:
            logger.error("Connection timeout")
            raise Exception('API connection timeout')
    
    @staticmethod
    async def is_username_available(username: str) -> bool:
        """
        Checks if a Minecraft username is available
        
        Args:
            username: The username to check
            
        Returns:
            True if username is available, False if taken
        """
        async def operation():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{MinecraftApiService.API_ENDPOINT}/{username}",
                        headers={'User-Agent': 'MinecraftAccountManager/1.0'},
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if response.status == 200:
                            return False  # Username is taken
                        elif response.status == 404:
                            return True  # Username is available
                        else:
                            raise aiohttp.ClientError(f"Unexpected status: {response.status}")
            except aiohttp.ClientResponseError as e:
                if e.status == 404:
                    return True  # Username is available
                raise
        
        return await MinecraftApiService.retry_operation(operation)
    
    @staticmethod
    def generate_random_usernames(length: int, count: int = 10) -> List[str]:
        """
        Generates random valid Minecraft usernames
        
        Args:
            length: The length of usernames to generate
            count: Number of usernames to generate
            
        Returns:
            List of generated usernames
        """
        import random
        
        usernames = set()
        letters = 'abcdefghijklmnopqrstuvwxyz'
        numbers = '0123456789'
        special = '_'
        
        max_attempts = count * 3
        attempts = 0
        
        while len(usernames) < count and attempts < max_attempts:
            username = ''
            
            # Start with a letter
            username += random.choice(letters)
            
            # Generate remaining characters
            for i in range(1, length):
                rand = random.random()
                if rand < 0.60:
                    username += random.choice(letters)
                elif rand < 0.95:
                    username += random.choice(numbers)
                else:
                    username += special
            
            if MinecraftApiService.is_valid_minecraft_username(username):
                usernames.add(username)
            
            attempts += 1
        
        return list(usernames)
    
    @staticmethod
    async def check_multiple_usernames(usernames: List[str]) -> List[Dict[str, Any]]:
        """
        Checks multiple usernames for availability with rate limiting
        
        Args:
            usernames: List of usernames to check
            
        Returns:
            List of dicts with username and availability status
        """
        results = []
        batch_size = 5
        delay_between_batches = 800  # milliseconds
        
        for i in range(0, len(usernames), batch_size):
            batch = usernames[i:i + batch_size]
            
            try:
                batch_results = await asyncio.gather(
                    *[
                        MinecraftApiService._check_username_with_result(username)
                        for username in batch
                    ],
                    return_exceptions=False
                )
                results.extend(batch_results)
            except aiohttp.ClientError as error:
                if hasattr(error, 'status') and error.status == 429:
                    await MinecraftApiService.delay(5000)
                    i -= batch_size
                    continue
                raise error
            
            if i + batch_size < len(usernames):
                await MinecraftApiService.delay(delay_between_batches)
        
        return results
    
    @staticmethod
    async def _check_username_with_result(username: str) -> Dict[str, Any]:
        """Helper to check username and return result dict"""
        try:
            available = await MinecraftApiService.is_username_available(username)
            return {'username': username, 'available': available}
        except Exception as e:
            logger.error(f"Error checking username {username}: {e}")
            return {'username': username, 'available': False, 'error': str(e)}
    
    @staticmethod
    async def get_player_info(username: str) -> Optional[Dict[str, Any]]:
        """
        Get player information from Mojang API
        
        Args:
            username: The username to look up
            
        Returns:
            Player information dict or None if not found
        """
        async def operation():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{MinecraftApiService.API_ENDPOINT}/{username}",
                        headers={'User-Agent': 'MinecraftAccountManager/1.0'},
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 404:
                            return None
                        else:
                            raise aiohttp.ClientError(f"Unexpected status: {response.status}")
            except aiohttp.ClientResponseError as e:
                if e.status == 404:
                    return None
                raise
        
        return await MinecraftApiService.retry_operation(operation)
