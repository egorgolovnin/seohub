"""Run this locally to generate a Telethon session string.

Usage:
    python scripts/gen_session.py

You'll need:
1. Go to https://my.telegram.org → API development tools
2. Get api_id and api_hash
3. Run this script, enter your phone and code
4. Copy the session string to TELETHON_SESSION_STRING env var
"""
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(input("Enter api_id: "))
    api_hash = input("Enter api_hash: ")

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()

    session_string = client.session.save()
    print(f"\n✅ Session string (save to TELETHON_SESSION_STRING):\n\n{session_string}\n")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
