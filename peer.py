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
import pandas as pd
from torch import channels_last, solve

from queue import Queue


class ElectChainPeer:
    def __init__(self):
        self.client = mqtt.Client()
        self.msg_queues = {
            'init': Queue(),
            'election': Queue(),
            'challenge': Queue(),
            'solution': Queue(),
            'voting': Queue()
        }

    def test_solution(seed, challenge):
        mask = BitArray('0b' + '1'*challenge).tobytes()
        mask += (20-len(mask))*b'\00'

        n_bytes = seed.to_bytes((seed.bit_length()+7)//8, 'big')
        hash_object = hashlib.sha1(n_bytes)
        hashed = hash_object.digest()

        xor = bytes([h & m for h,m in zip(hashed, mask)])

        return  not bool.from_bytes(xor, "big")

    def push_msg_queues(self, client, userdata, message):
        topic = message.topic
        body = json.loads(message.payload)

        self.msg_queues[topic].put(body)

    def init(self):
        message = json.dumps({
            'id': self.id
        })
        self.client.publish('init', message)

        init_msgs = []
        while len(init_msgs) < 10:
            id = self.msg_queues['init'].get()['id']

            if id not in init_msgs:
                init_msgs.append(id)
                self.client.publish('init', message)

        self.state = 'election'

    def elect(self):
        message = json.dumps({
            'election': random.randint(0, 255),
            'id': self.id
        })
        self.client.publish('election', message)

        election = []
        for _ in range(10):
            election.append(self.msg_queues['election'].get())

        leader = sorted(election, key=operator.itemgetter('election', 'id'))[-1]
        self.current_leader = leader['id']

        self.state = 'challenge'
    
    def challenge(self):
        if self.current_leader == self.id:
            challenge = random.randint(1,120)

            message = json.dumps({
                'id': self.id,
                'challenge': challenge
            })
            self.client.publish('challenge', message)
        
            print(f'{self.id}: Current leader. Challenge is {challenge}')
        
        challenge_msg = self.msg_queues['challenge'].get()
        while challenge_msg['id'] != self.current_leader:
            challenge_msg = self.msg_queues['challenge'].get()

        self.current_challenge = challenge_msg['challenge']
        
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

        self.mining_processes = []
        n = seed.value

        if n == -1: return

        hashed = hashlib.sha1(n.to_bytes((n.bit_length()+7)//8, 'big')).digest()
        print(f'{self.id}: Found seed: {n} - {hashed}')

        message = json.dumps({
            'id': self.id,
            'transaction': self.current_transaction,
            'seed': n
        })
        self.client.publish('solution', message)

    def validate(self):
        solved = False
        solution = None
        while not solved:
            solution = self.msg_queues['solution'].get()

            transaction = solution['transaction']
            seed = solution['seed']
            challenge = self.transactions[transaction]['challenge']

            solved = ElectChainPeer.test_solution(seed, challenge)
            message = json.dumps({
                'id': self.id,
                'transaction': transaction,
                'seed': seed,
                'vote': solved
            })
            self.client.publish('voting', message)
        
        self.current_solution = solution
        print(f'{self.id}: Solution {solution["seed"]} for transaction {solution["transaction"]} from {solution["id"]} passes.')

        for p in self.mining_processes:
            try:
                p.terminate()
            except:
                pass

        self.mining_processes = []

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
        vote_count = 0

        for _ in range(10):
            vote_msg = self.msg_queues['voting'].get()

            vote = vote_msg['vote']

            if vote: vote_count += 1

        if vote_count >= 6:
            print(f'{self.id}: {self.current_solution["id"]} wins transaction {self.current_solution["transaction"]}.')
            self.state = 'update'
        else:
            self.state = 'running'

    def update(self):
        seed = self.current_solution['seed']
        id = self.current_solution['id']
        self.transactions[self.current_transaction]['seed'] = str(seed)
        self.transactions[self.current_transaction]['winner'] = id

        self.current_transaction += 1
        
        self.state = 'challenge'

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

        self.client.subscribe('challenge')
        self.client.subscribe('election')
        self.client.subscribe('solution')
        self.client.subscribe('voting')
        self.client.subscribe('init')

        self.client.on_message = self.push_msg_queues

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

            elif self.state == 'update':
                self.update()
                print(pd.DataFrame().from_dict(self.transactions))

            else:
                break
        self.client.loop_stop()

if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print('Usage:\n\tpython peer.py [broker_address]')
        sys.exit()

    address = sys.argv[1]
    elect_chain_peer = ElectChainPeer()
    elect_chain_peer.connect(address)
    elect_chain_peer.run()
