from SpoonsClient import *
import sys

def main():
    if len(sys.argv) != 2:
        print('Invalid number of arguments')
        print('Usage: python3 PlaySpoons.py <GAME_NAME>')
        exit(1)
    else:
        game_name = sys.argv[1]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    player = SpoonsClient(game_name)
    loop.run_until_complete(player.run())
    #loop.close()
    # try:
    #     loop.run_forever()
    # except KeyboardInterrupt:
    #     pass
    # finally:
    #     loop.close()
    

if __name__=='__main__':
    main()