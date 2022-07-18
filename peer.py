import hashlib
import json
import operator
import os
import random
import sys
import time
from multiprocessing import Process, Value
from threading import Event, Thread

import paho.mqtt.client as mqtt
from bitstring import BitArray
from torch import channels_last, solve

from async_message_queue import AsyncMessageQueue


class ElectChainPeer:
    def __init__(self):
        self.client = mqtt.Client()
        self.event_objects = {
            'init': Event(),
            'election': Event(),
            'challenge': Event(),
            'sync': Event(),
            'validate': Event(),
            'voting': Event()
        }

    def test_solution(seed, challenge):
        mask = BitArray('0b' + '1'*challenge).tobytes()
        mask += (20-len(mask))*b'\00'

        n_bytes = seed.to_bytes((seed.bit_length()+7)//8, 'big')
        hash_object = hashlib.sha1(n_bytes)
        hashed = hash_object.digest()

        xor = bytes([h & m for h,m in zip(hashed, mask)])

        return  not bool.from_bytes(xor, "big")

    def sync(self, client, userdata, message):
        self.sync_count += 1
        if self.sync_count == 10:
            self.sync_count = 0
            self.event_objects['sync'].set()

    def listen_init(self, client, userdata, message):

        received_id = int.from_bytes(message.payload, 'big')
        if received_id not in self.hellos:
            self.hellos.append(received_id)
            self.client.publish('init', self.id)

        if len(self.hellos) == 10 and not self.got_all:
            self.event_objects['init'].set()
            self.got_all = True

    def listen_elect(self, client, userdata, message):
        body = json.loads(message.payload)

        if len(self.elections) == 10:
            self.elections = []

        self.elections.append((body['id'], body['election']))

        if len(self.elections) == 10:
            self.event_objects['election'].set()
    
    def listen_challenge(self, client, userdata, message):
        body = json.loads(message.payload)

        if body['id'] == self.current_leader:
            self.current_challenge = body['challenge']
            self.event_objects['challenge'].set()

    def listen_solution(self, client, userdata, message):
        body = json.loads(message.payload)

        if self.current_solution == None and ElectChainPeer.test_solution(body['seed'], self.current_challenge):
            self.current_solution = (body['id'], body['seed'])
        
        self.event_objects['validate'].set()

    def listen_voting(self, client, userdata, message):
        body = json.loads(message.payload)

        transaction = str(body['transaction'])
        seed = str(body['seed'])

        if transaction not in self.current_votes:
            self.current_votes[transaction] = {}
            self.current_votes[transaction][seed] = {'yes': 0, 'no': 0}
        elif seed not in self.current_votes[transaction]:
            self.current_votes[transaction][seed] = {'yes': 0, 'no': 0}

        if body['vote']:
            self.current_votes[transaction][seed]['yes'] += 1
        else:
            self.current_votes[transaction][seed]['no'] += 1

        total = self.current_votes[transaction][seed]['yes'] + self.current_votes[transaction][seed]['no']

        if total == 10:
            self.event_objects['voting'].set()

    def init(self):
        self.client.publish('init', self.id)

        flag = self.event_objects['init'].wait(10)
        if not flag:
            print(f'{self.id}: Timeout waiting for init messages. Exitting...')
            sys.exit()

        self.event_objects['init'].clear()
        self.state = 'election'

    def elect(self):

        body = {
            'election': random.randint(0, 255),
            'id': self.id
        }

        message = json.dumps(body)
        self.client.publish('election', message)

        flag = self.event_objects['election'].wait(10)
        if not flag:
            print(f'{self.id}: Timeout waiting for elections. Exitting...')
            sys.exit()

        self.event_objects['election'].clear()
        elected = sorted(self.elections, key=operator.itemgetter(1, 0))[-1]
        self.current_leader = elected[0]

        body = {
            'id': self.id
        }

        message = json.dumps(body)
        self.client.publish('sync', message)

        flag = self.event_objects['sync'].wait(10)
        if not flag:
            print(f'{self.id}: Timeout waiting for sync. Exitting...')
            sys.exit()
        self.event_objects['sync'].clear()

        self.state = 'challenge'
    
    def challenge(self):

        if self.current_leader == self.id:
            # challenge = random.randint(1,120)
            challenge = 20

            body = {
                'id': self.id,
                'challenge': challenge
            }

            message = json.dumps(body)
            self.client.publish('challenge', message)
            self.current_challenge = challenge
        
            print(f'{self.id}: Current leader. Challenge is {self.current_challenge}')

        flag = self.event_objects['challenge'].wait(10)
        if not flag:
            print(f'{self.id}: Timeout waiting for challenge. Exitting...')
            sys.exit()

        self.event_objects['challenge'].clear()
        
        self.transactions.append({'transaction_id': self.current_transaction,'challenge': self.current_challenge,'seed': '', 'winner': -1})
        self.state = 'running'

    def parallel_mine(self, n, step, mask, seed):
        while seed.value == -1:
            n_bytes = n.to_bytes((n.bit_length()+7)//8, 'big')
            hash_object = hashlib.sha1(n_bytes)
            hashed = hash_object.digest()

            xor = bytes([h & m for h,m in zip(hashed, mask)])

            if not bool.from_bytes(xor, "big"):
                seed.value = n
            
            n += step

    def mine(self):
        mask = BitArray('0b' + '1'*self.current_challenge).tobytes()
        mask += (20-len(mask))*b'\00'

        thread_count = os.cpu_count()
        self.mining_processes = []

        seed = Value('i', -1)
        for n in range(thread_count):
            p = Process(target=self.parallel_mine, args=(n, thread_count, mask, seed))
            self.mining_processes.append(p)
            p.start()
        
        for p in self.mining_processes:
            p.join()

        n = seed.value

        if n == -1: return

        hashed = hashlib.sha1(n.to_bytes((n.bit_length()+7)//8, 'big')).digest()
        print(f'{self.id}: Found seed: {n} - {hashed}')

        body = {
            'id': self.id,
            'transaction': self.current_transaction,
            'seed': n
        }
        message = json.dumps(body)
        self.client.publish('solution', message)

    def validate(self):
        while self.current_solution == None:

            self.event_objects['validate'].wait()
            self.event_objects['validate'].clear()

            if self.current_solution == None:
                body = {
                    'id': self.id,
                    'transaction': self.current_transaction,
                    'seed': self.current_solution[1],
                    'vote': False
                }
                message = json.dumps(body)
                self.client.publish('voting', message)
        
        body = {
            'id': self.id,
            'transaction': self.current_transaction,
            'seed': self.current_solution[1],
            'vote': True
        }
        message = json.dumps(body)
        self.client.publish('voting', message)

        print(f'{self.id}: Solution {self.current_solution[1]} from {self.current_solution[0]} passes.')

        for p in self.mining_processes:
            p.terminate()

    def runnig(self):
        self.current_solution = None
        self.mining_processes = []

        mining_thread = Thread(target=self.mine)
        validating_thread = Thread(target=self.validate)

        validating_thread.start()
        mining_thread.start()

        mining_thread.join()
        validating_thread.join()

        self.state = 'voting'

    def voting(self):
        flag = self.event_objects['voting'].wait(5)
        if not flag:
            print('Timeout')
            sys.exit()
        self.event_objects['voting'].clear()

        print('Voted')

        transaction = str(self.current_transaction)
        seed = str(self.current_solution[1])

        if self.current_votes[transaction][seed]['yes'] >= 6:
            print(f'{self.id}: Solution {self.current_solution[1]} from {self.current_solution[0]} wins.')
            self.state = 'update'
        else:
            print(f'{self.id}: Solution {self.current_solution[1]} from {self.current_solution[0]} loses.')
            self.state = 'running'

    def connect(self, broker_address):
        self.id = time.time_ns()
        self.broker_address = broker_address
        self.client.connect(broker_address)
        print(f'{self.id}: Connected to broker')
    
    def run(self):
        print(f'{self.id}: Started transaction mining')

        self.sync_count = 0
        self.hellos = []
        self.elections = []
        self.current_leader = None
        self.current_challenge = None
        self.init_responses = 0
        self.state = 'init'
        self.got_all = False
        self.current_solution = None
        self.current_votes = {}

        self.transactions = []
        self.current_transaction = 0

        self.client.subscribe('sync')
        self.client.subscribe('challenge')
        self.client.subscribe('election')
        self.client.subscribe('solution')
        self.client.subscribe('voting')
        self.client.subscribe('init')

        self.client.message_callback_add('init', self.listen_init)
        self.client.message_callback_add('election', self.listen_elect)
        self.client.message_callback_add('challenge', self.listen_challenge)
        self.client.message_callback_add('solution', self.listen_solution)
        self.client.message_callback_add('voting', self.listen_voting)
        self.client.message_callback_add('sync', self.sync)

        self.client.loop_start()
        if self.state == 'init':
            self.init()
            print(f'{self.id}: Received all init messages')
        
        if self.state == 'election':
            self.elect()
            print(f'{self.id}: Received all election messages. Leader is {self.current_leader}')
        while True:
            if self.state == 'challenge':
                self.challenge()
                print(f'{self.id}: Received challenge {self.current_challenge}')

            elif self.state == 'running':
                self.runnig()

            elif self.state == 'voting':
                self.voting()

            else:
                break
        self.client.loop_stop()

elect_chain_peer = ElectChainPeer()
elect_chain_peer.connect('127.0.0.1')
elect_chain_peer.run()
