import sys
import socket
import json
import http.client
import time
import asyncio
from functools import partial
from concurrent.futures.thread import ThreadPoolExecutor

class SpoonException(Exception):
	pass

class SpoonsClient:
	heart = "\u2665"
	club = "\u2663"
	diamond = "\u2666"
	spade = "\u2660"

	def __init__(self, game_name):
		self.game_name = game_name
		self.host = None
		self.port = 0
		self.lastheardfrom = 0
		self.name_retries = 0
		self.server_retries = 0
		self.send_retries = 0
		self.recv_retries = 0
		self.id = -1
		self.grabbing_started = 0
		self.eliminated = 0
		self.reader = None
		self.writer = None
		self.host = None

		self.mycards = []
		
	async def run(self):
		await self.connect_to_server()
		# Read for the start of the game
		resp = await self.recv_resp({"dummy": "dummy"})
		if resp['method'] == 'start_game':
			print("Game is starting")
			await self.play_game()

	async def listen(self, port, ip):
		loop = asyncio.get_event_loop()
		remote_addr=('0.0.0.0', 9004)
		listen = loop.create_datagram_endpoint(lambda: SimpleUDPProtocol(), remote_addr=remote_addr)
		self.transport, self.protocol = await listen

	def find_name(self):
		while (True):
			name_server = http.client.HTTPConnection('catalog.cse.nd.edu', '9097')
			name_server.request('GET', '/query.json')
			name_server_entries = json.loads(name_server.getresponse().read().decode())

			for entry in name_server_entries:
				try:
					if self.host == None and entry['game_name'] == self.game_name: # save the first match
						self.host = entry['host']
						self.port = entry['port']
						self.lastheardfrom = entry['lastheardfrom']

					elif entry['game_name'] == self.game_name:   # if exist more matches --> check lastheardfrom
						if entry['lastheardfrom'] > self.lastheardfrom:
							self.host = entry['host']
							self.port = entry['port']
							self.lastheardfrom = entry['lastheardfrom']
					
				except KeyError as ke:
					pass

			if self.host == None:
				print('Failed to lookup name in catalog. Trying lookup again.')
				time.sleep(2**self.name_retries)
				self.name_retries+=1
				continue
			else:
				break

	async def connect_to_server(self):
		self.find_name()

		self.server_retries = 0
		self.reader, self.writer = await asyncio.open_connection(self.host, int(self.port))
		
		msg = {'method': 'join_game'}
		msg = json.dumps(msg)
		await self.send_request(msg)
		resp = await self.recv_resp(msg)
		self.id = int(resp['id'])

		print('Welcome! You are player ' + str(self.id) + '!')
		if self.id == 0:
			print('\nYou are the first player in the circle! You will be picking up from the remaining deck and will begin the flow of cards.')

	async def get_user_input(self):
		return await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)


	async def play_game(self):
		print(f"Starting game..")
		await self.get_cards()
		spoon_listen = partial(asyncio.get_event_loop().run_in_executor, ThreadPoolExecutor(1))

		while(self.grabbing_started == 0):

			print('\nYOUR HAND:')
			self.display_cards(self.mycards, 1)

			# wait for both user input and spoon notification using task list and wait
			tasks = [asyncio.wait([spoon_listen(await self.wait_on_broadcast())])]
			done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

			# check for spoon notification in completed tasks
			if done:
				try:
					spoon_notif = done.pop().result()
				except:
					pass
				try:
					if spoon_notif[0] == 'grab_spoon':
						print('grab a spoon')
						await self.grab_spoon()
						continue
				except:
					pass
				

			method = input("Enter 'p' to pickup next card\nEnter 'x' to try to grab a spoon\n")

			if method != 'p' and method != 'x':
				print('Invalid operation')
				continue
			if method == 'x':
				await self.grab_spoon()
			if method == 'p':
				new_card = await self.pickup()
				if new_card == 'next_round':
					return
				elif new_card == 'eliminated':
					return

				elif new_card is None:
					print('No cards in pick up deck yet. Try again.')
					continue
				self.mycards.append(new_card)
				print('NEW CARD:')
				self.display_cards([new_card], 1)

				for i, card in enumerate(self.mycards):
					print(str(i) + ': ', end='')
					self.display_cards([card], 0)

				ind = input("\tEnter card to discard (0-4): ")
				while ind not in ['0', '1', '2', '3', '4']:
					print('\tInvalid card selected.')
					ind = input("\tEnter card to discard (0-4): ")
				ind = int(ind)
				discard_card = self.mycards[ind]
				resp = await self.discard(discard_card)
				if resp == 'next_round' or resp == 'eliminated':
					return
				self.mycards.remove(discard_card)
			sys.stdout.flush()

	
	async def wait_on_broadcast(self):
		msg = { 'method': 'want_broadcast'}
		msg = json.dumps(msg)
		await self.send_request(msg)
		resp = await self.recv_resp(msg)
		if resp['method'] =='grab_spoon':
			self.grabbing_started = 1
			return 1
		else:
			return 0
	

	async def grab_spoon(self):
		get_input = partial(asyncio.get_event_loop().run_in_executor, ThreadPoolExecutor(1))

		print("Are you ready to grab a spoon?")
		wantSpoon = await get_input(input, "ENTER x TO GRAB SPOON! ")
		# user gets correct card line up and grabs spoon
		if wantSpoon.strip() == 'x':
			# first person to grab spoon
			if self.four_of_a_kind() and self.grabbing_started == 0:
				self.grabbing_started = 1
				#t = time.time_ns()
				msg = { 'method': 'grab_spoon'}
				msg = json.dumps(msg)
				await self.send_request(msg)
				
				resp = await self.recv_resp(msg)
				status = resp['status']
				if status == 'success':
					if resp['result'] == 'game_over':
						print("You got the last spoon. You win!!")
					else:
						print("You successfully grabbed a spoon!\nWait for the other players to grab the spoons for the next round.")
			elif self.four_of_a_kind() == 0 and self.grabbing_started == 0:
				print("\nInvalid cards to grab spoon. Keep playing!")
				return
			elif self.grabbing_started == 1:
				msg = { 'method': 'grab_spoon'}
				msg = json.dumps(msg)
				await self.send_request(msg)

				server_ack = await self.recv_resp(msg)

				if server_ack['result'] == 'next_round':
					print('SUCCESS!')
					print('\tYou successfully grabbed a spoon. Moving on to the next round.')
					return 'next_round'
				elif server_ack['result'] == 'eliminated':
					print('TOO SLOW')
					print('\tYou were last to grab a spoon. You have been ELIMINATED.')
					self.eliminated = 1
					return 'eliminated'
		else:
			# in case user doesnt press x but grabbing has begun
			if(self.grabbing_started==1):
				print("Are you sure you don't want to grab a spoon?\n")
				self.grab_spoon()
			else: # keep playing
				return

	async def get_cards(self):
		msg = { 'method': 'get_cards' }
		msg = json.dumps(msg)
		await self.send_request(msg)
		resp = await self.recv_resp(msg)
		self.mycards = resp['cards']

	async def pickup(self):
		msg = { 'method': 'pickup' }
		msg = json.dumps(msg)
		await self.send_request(msg)
		resp = await self.recv_resp(msg)
		if resp['method'] == 'grab_spoon':
			self.grabbing_started = 1
			x = input('GRABBING STARTED!\n\tENTER x TO GRAB! : ')
			return self.grab_spoon()
		
		if resp['result'] == 'success':
			return resp['card']
		else:
			return None

	async def discard(self, card):
		msg = { 'method': 'discard', 'card': card}
		msg = json.dumps(msg)
		await self.send_request(msg)
		resp = await self.recv_resp(msg)
		if resp['method'] == 'grab_spoon':
		   self.grabbing_started = 1
		   x = input('GRABBING STARTED!\n\tENTER x TO GRAB!')
		   return self.grab_spoon()
		return None
  
	async def send_request(self, msg):
		length = str(len(msg)).encode()
		msg = msg.encode()
		self.writer.write(length + msg)
		await self.writer.drain()
		

	async def recv_resp(self, msg):
		data = await self.reader.read(4096)
		resp = json.loads(data.decode())
		return resp

	def four_of_a_kind(self):
		if self.mycards[0][:-1] == self.mycards[1][:-1] == self.mycards[2][:-1] == self.mycards[3][:-1]:
			return 1
		return 0


	def display_cards(self, cards, graphics):
		suits = [0,0,0,0]
		tens = [0,0,0,0] # array of booleans saying if its a ten or not

		if(len(cards) == 4):

			for index, card in enumerate(cards):
				if card[-1:] == 'H':
					suits[index] = self.heart
				elif card[-1:] == 'C':
					suits[index] = self.club
				elif card[-1:] == 'D':
					suits[index] = self.diamond
				elif card[-1:] == 'S':
					suits[index] = self.spade
				if card[:-1] == '10':
					tens[index]=1
				else:
					tens[index]=0

			if graphics:
				# check that tens works
				# adjust for different spacing with 10 (two digit number)
				print(f'\t+-----+\t\t+-----+\t\t+-----+\t\t+-----+\t\t')
				if tens[0]==1:
					print(f'\t|{cards[0][:-1]}   |\t', end='')
				else:
					print(f'\t|{cards[0][:-1]}    |\t', end='')
				if tens[1]==1:
					print(f'\t|{cards[1][:-1]}   |\t', end='')
				else:
					print(f'\t|{cards[1][:-1]}    |\t', end='')
				if tens[2]==1:
					print(f'\t|{cards[2][:-1]}   |\t', end='')
				else:
					print(f'\t|{cards[2][:-1]}    |\t', end='')
				if tens[3]==1:
					print(f'\t|{cards[3][:-1]}   |\t\t')
				else:
					print(f'\t|{cards[3][:-1]}    |\t\t')
				print(f'\t|{suits[0]}    |\t\t|{suits[1]}    |\t\t|{suits[2]}    |\t\t|{suits[3]}    |\t\t')
				print(f'\t|     |\t\t|     |\t\t|     |\t\t|     |\t\t')
				print(f'\t+-----+\t\t+-----+\t\t+-----+\t\t+-----+\t\t')
			else:
				print(f'{card[:-1]}{suit}')


		else:

			for card in cards:
				if card[-1:] == 'H':
					suit = self.heart
				elif card[-1:] == 'C':
					suit = self.club
				elif card[-1:] == 'D':
					suit = self.diamond
				elif card[-1:] == 'S':
					suit = self.spade

				if graphics:
					# adjust for different spacing with 10 (two digit number)
					if card[:-1] == '10':
						print(f'\t+-----+\n\t|{card[:-1]}   |\n\t|{suit}    |\n\t|     |\n\t+-----+')
					else:
						print(f'\t+-----+\n\t|{card[:-1]}    |\n\t|{suit}    |\n\t|     |\n\t+-----+')
				else:
					print(f'{card[:-1]}{suit}')