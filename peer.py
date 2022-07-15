import json
import operator
import random
import time

import paho.mqtt.client as mqtt


class ElectChainPeer:
    def __init__(self):
        self.id = time.time_ns()
        self.client = mqtt.Client()

    def listen_init(self, client, userdata, message):
        received_id = int.from_bytes(message.payload, 'big')
        if received_id not in self.hellos:
            self.hellos.append(received_id)

        if len(self.hellos) == 10 and not self.got_all:
            self.got_all = True
            print(f'{self.id} got all responses')
        
    def listen_elect(self, client, userdata, message):
        body = json.loads(message.payload)

        if len(self.elections) == 10:
            self.elections = []

        self.elections.append((body['id'], body['election']))
    
    def listen_challenge(self, client, userdata, message):
        body = json.loads(message.payload)

        if body['id'] == self.current_leader:
            self.current_challenge = body['challenge']

    def init(self):
        self.client.loop_start()
        while len(self.hellos) < 10:
            time.sleep(0.5)
            self.client.publish('init', self.id)
        self.client.loop_stop()

    def elect(self):
        body = {
            'election': random.randint(0, 255),
            'id': self.id
        }

        message = json.dumps(body)
        self.client.publish('election', message)

        self.client.loop_start()
        # FIXUP: We should be sleeping untill there are 10 election messages
        while len(self.elections) < 10:
            time.sleep(0.5)
        self.client.loop_stop()

        elected = sorted(self.elections, key=operator.itemgetter(1, 0))[-1]
        self.current_leader = elected[0]

        print(f'Elected {elected[0]} with election {elected[1]}')
    
    def challenge(self):
        if self.current_leader == self.id:
            challenge = random.randint(1,120)

            body = {
                'id': self.id,
                'challenge': challenge
            }

            message = json.dumps(body)
            self.client.publish('challenge', message)
            self.current_challenge = challenge
        
            print(f'Current leader {self.id} says: challenge = {challenge}')

        else:
            self.client.loop_start()
            while self.current_challenge == None:
                time.sleep(0.5)
            self.client.loop_stop()

            print(f'Received challenge = {self.current_challenge}')

    def connect(self, broker_address):
        self.broker_address = broker_address
        self.client.connect(broker_address)

        print(f'I\'m peer {self.id} and i\'m connected!')

        self.hellos = []
        self.elections = []
        self.current_leader = None
        self.current_challenge = None
        self.init_responses = 0
        self.state = 'init'
        self.got_all = False

        self.client.subscribe('challenge')
        self.client.subscribe('election')
        self.client.subscribe('init')

        self.client.message_callback_add('init', self.listen_init)
        self.client.message_callback_add('election', self.listen_elect)
        self.client.message_callback_add('challenge', self.listen_challenge)

        self.init()
        self.elect()
        self.challenge()
 
    
    def loop(self):
        self.client.loop_forever()

elect_chain_peer = ElectChainPeer()
elect_chain_peer.connect('127.0.0.1')
