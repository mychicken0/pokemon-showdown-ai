#!/usr/bin/env python3
import asyncio

from poke_env import AccountConfiguration

from bot_doubles_damage_aware import DoublesDamageAwarePlayer


BOT_NAME = "SinB_Doubles_AI"
CHALLENGER = "player_test_local"


async def main():
    bot = DoublesDamageAwarePlayer(
        account_configuration=AccountConfiguration(BOT_NAME, None),
        battle_format="gen9randomdoublesbattle",
        max_concurrent_battles=1,
        verbose=True,
    )
    battle_number = 1
    while True:
        print(
            f"{BOT_NAME} is online. Waiting for "
            f"gen9randomdoublesbattle challenge #{battle_number} "
            f"from {CHALLENGER}..."
        )
        try:
            await bot.accept_challenges(CHALLENGER, n_challenges=1)
        except Exception as error:
            print(f"Challenge/battle error: {error!r}. Returning to listen mode.")
            await asyncio.sleep(1)
            continue
        print(f"Battle #{battle_number} finished.")
        battle_number += 1


if __name__ == "__main__":
    asyncio.run(main())
