import sys
import socket
import json
import os
import select
from CardDeck import *
import time
import asyncio


class SimpleUDPProtocol(asyncio.DatagramProtocol):
	def connection_made(self, transport):
		self.transport = transport

	def datagram_received(self, data, addr):
		text = data.decode("utf-8").strip()
		response = json.loads(text)
		print(f"Received from Name Server: {response}")

class SpoonsServer:
	def __init__(self, game_name, expected_players):
		self.port                = 9001
		self.game_name           = game_name
		self.last_sent           = 0
		self.spoons              = 3
		self.BroadCastQueue      = []
		self.grab_time_stamp     = {}
		self.players             = []
		self.players_info        = {}
		self.expected_players    = expected_players
		self.num_players         = 0
		self.num_spoons          = 0
		self.deck                = CardDeck()
		self.discard_pile        = []
		self.timeSpoonGrabbed    = -1
		self.first_spoon_grabbed = 0
		self.moving_forward      = []
		self.host = None
	
	async def run(self):
		# init name server socket and main socket
		await self.init_name_server()
		await self.init_server()
	
	def schedule_udp(self):
		# send UDP msg to name server every 60 seconds
		num_sec = 60
		asyncio.ensure_future(self.send_udp())
		loop = asyncio.get_event_loop()
		loop.call_later(num_sec, self.schedule_udp)
		 
	async def init_server(self):
		self.game_init_time = time.time_ns()
		self.game_over = 0
		server = await asyncio.start_server(self.handle_client, '127.0.0.1', self.port)
		self.host = server.sockets[0].getsockname()[0]
		print(f"Listening on {self.host}:{self.port}")
		self.schedule_udp()
		async with server:
			await server.serve_forever()

	async def handle_client(self, reader, writer):
		# handle client each time one sends a request
		client_addr   = writer.get_extra_info("peername")
		client_fileno = writer.get_extra_info("socket").fileno()

		while True:
			bytes_to_read = await reader.read(2)
			bytes_to_read = int.from_bytes(bytes_to_read, byteorder="big")
			data = await reader.read(bytes_to_read)
			msg  = data.decode("utf-8")
			
			await self.execute_msg(client_fileno, client_addr, writer, msg)
		await writer.wait_closed()

	async def init_name_server(self):
		# init the name server socket
		loop = asyncio.get_event_loop()
		remote_addr=(socket.gethostbyname('catalog.cse.nd.edu'), 9097)
		listen = loop.create_datagram_endpoint(lambda: SimpleUDPProtocol(), remote_addr=remote_addr)
		self.transport, self.protocol = await listen

	async def init_game(self):
		# send a "start_game" to all users
		tasks = []
		msg = json.dumps({"method": "start_game"})
		for player in self.players_info:
			tasks.append(self.send_msg(player, msg))
		await asyncio.gather(*tasks)

		self.num_spoons = self.num_players - 1
		self.deal_cards()
		self.players_info[self.players[0]]['pickup_deck'] = self.deck.remaining_cards

		# set pickup pile of player #0 to be remaining_cards in deck object
		self.players_info[self.players[0]]['pickup_deck'] = self.deck.remaining_cards

	# adds a player to player_info and intiializes it's values
	def init_player_info(self, player, num, writer):
		self.players_info[player] = {
										'id': num,
										'writer': writer,
										'cards': [],
										'pickup_deck': [],
										'player_num': self.num_players,
										'spoon_grabbed': 0,
										'player_name': '',
										'grab_time_stamp': -1
									}

	async def execute_msg(self, player, player_addr, writer, msg):
		try:
			msg = json.loads(msg)
		except:
			pass
		method = msg['method']

		if method == "join_game":
			# Handle if game already started...
			if self.num_players +1 > self.expected_players:
				resp = { 'method': 'join_game', 'status': 'reject', 'reason': 'game_already_started' }
				writer.write(json.dumps(resp).encode('utf-8'))
				await writer.drain()
				return
			self.init_player_info(player, self.num_players, writer)
			self.players.append(player)
			print(f"\tPlayer {self.num_players} joined!")

			resp = { 'method': 'join_game', 'status': 'success', 'id': self.num_players }

			# If there is an expected # of players, start running the game in the background
			self.num_players += 1
			if self.num_players  >= self.expected_players:
				print("Starting game...")
				asyncio.ensure_future(self.init_game())

		elif method == 'want_broadcast':
			if self.first_spoon_grabbed == 0:
				resp = { 'method': 'continue'}
			else:
				resp = { 'method': 'grab_spoon'}
		if method == 'get_cards':
			resp = { 'method': 'get_cards', 'result': 'success', 'cards': self.players_info[player]['cards'] }
			
		elif method == 'pickup':
			if len(self.players_info[player]['pickup_deck']) == 0:

				if player == self.players[0]:
					if self.discard_pile == []:
						resp = { 'method': 'pickup', 'result': 'failure', 'message': 'No cards in pickup deck. Try again.' }
						writer.write(json.dumps(resp).encode())
						await writer.drain()
					else:
						self.players_info[player]['pickup_deck'] = self.discard_pile
						self.discard_pile = []
				else:
					resp = { 'method': 'pickup', 'result': 'failure', 'message': 'No cards in pickup deck. Try again.' }

			new_card = self.players_info[player]['pickup_deck'].pop()
			self.players_info[player]['cards'].append(new_card)
			resp = { 'method': 'pickup', 'result': 'success', 'card': new_card }

		elif method == 'discard':

			self.players_info[player]['cards'].remove(msg['card'])
			next_ind = self.players_info[player]['player_num'] + 1

			# if last player, go to discard pile
			if next_ind == self.num_players:
				self.discard_pile.append(msg['card'])
			# else into next player's pickup deck
			else:
				self.players_info[self.players[next_ind]]['pickup_deck'].append(msg['card'])
			resp = { 'method': 'discard', 'result': 'success' }
			
		elif method == 'grab_spoon':  
			# first spoon to be grabbed, enter spoon_thread for broadcast and grabbing spoon event
			if self.first_spoon_grabbed == 0:
				await self.spoons_thread(self.players_info[player],msg)
		
		writer.write(json.dumps(resp).encode())
		await writer.drain()
		

			
	async def spoons_thread(self, player, msg):
		# first spoon is grabbed

		if self.num_spoons == self.num_players - 1: # need to broadcast to everyone else to get spoon, and that first grabber got it
			msg = {'method': "grab spoon"}
			self.last_sent = time.time_ns()
			self.num_spoons -= 1
			
			self.players_info[player['writer'].get_extra_info("socket").fileno()]["spoon_grabbed"] = 1
			self.first_spoon_grabbed = 1
			if self.num_players>2:
				ack_msg = {'method': "grab_spoon", 'status': 'success','result': 'next_round','spoons_left': self.num_spoons}
			else:
				ack_msg = {'method': "grab_spoon", 'status': 'success','result': 'game_over'}
			response = json.dumps(ack_msg)
			await self.send_msg(player['writer'].get_extra_info("socket").fileno(), response)
			
			tasks = []
			for p in self.players_info:
				if not self.players_info[p]["spoon_grabbed"]:
					msg = {'method': "grab_spoon"}
					msg = json.dumps(msg)
					tasks.append(self.send_msg(p, msg))

			await asyncio.gather(*tasks)
		
		# Not first spoon but still spoons left
		elif self.num_spoons > 0:
			self.num_spoons -= 1
			self.players_info[player]["spoon_grabbed"] = 1
			self.players_info[player]["grab_time_stamp"] = float(msg["time"])
			ack_msg = {'method': "grab_spoon", 'status': 'success','spoons_left': self.num_spoons}
			response = json.dumps(ack_msg)
			await self.send_msg(player, response)

		# No spoons left, player is eliminated
		else:
			# send message to player that they are eliminated and that new round is starting
			ack_msg = {'method': "grab_spoon", 'status': 'failure', 'message': 'You are eliminated!'}
			response = json.dumps(ack_msg)
			await self.send_msg(player['writer'].get_extra_info("socket").fileno(), response)

			# Send message to all other players that new round is starting
			ack_msg = {'method': "new_round", 'result': 'new_round', 'message': 'New round starting!'}
			tasks = []
			for p in self.players_info:
				msg = json.dumps(ack_msg)
				tasks.append(self.send_msg(p, msg))
			await asyncio.gather(*tasks)
			# start new round

			# Remove player from game
			self.num_players -= 1
			self.players.remove(player['writer'].get_extra_info("socket").fileno())
			self.players_info.pop(player['writer'].get_extra_info("socket").fileno())

			self.start_next_round()
			

	async def send_msg(self, player, msg):
		writer = self.players_info[player]["writer"]
		writer.write(msg.encode())
		await writer.drain()

	# move onto the next round with eliminated player removed, one less spoon, new shuffled hands
	def start_next_round(self):
		# what we need reset at beginning of each new round
		self.BroadCastQueue = []
		self.grab_time_stamp = {}
		self.deck = CardDeck()
		self.discard_pile = []
		self.timeSpoonGrabbed = -1
		self.first_spoon_grabbed = 0
		self.remaining_cards = []
		self.deal_cards()
		self.first_spoon_grabbed = 0
		self.num_spoons = self.num_players - 1

		for i, player in enumerate(self.players):
			self.init_player_info(player, i, self.players_info[player]['writer'].get_extra_info("socket").fileno())
		print("Starting next round...")
		asyncio.ensure_future(self.init_game())

	def deal_cards(self):
		hands = self.deck.deal_cards(self.num_players)
		for i, player in enumerate(self.players_info.values()):
			player['cards'] = hands[i]

	async def send_udp(self):
		# send UDP msg to name server		
		msg = { "type" : "hashtable", "owner" : "mnovak5", "host": self.host, "port" : self.port, "game_name" : self.game_name }
		self.transport.sendto(json.dumps(msg).encode())
		self.last_sent = time.time_ns()

		
async def main():
	if len(sys.argv) != 3:
		print('Invalid number of arguments')
		print('Usage: python3 SpoonsServer.py <GAME_NAME> <NUM_PLAYERS>')
		exit(1)
	else:
		game_name = sys.argv[1]
		num_players = int(sys.argv[2])

	if num_players < 2:
		print('Need at least 2 players')
		exit(1)

	ss = SpoonsServer(game_name, num_players)
	await ss.run()
	

if __name__ == '__main__':
	asyncio.run(main())