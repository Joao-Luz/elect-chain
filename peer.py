import json
import operator
import random
import sys
import time

import paho.mqtt.client as mqtt
from threading import Event


class ElectChainPeer:
    def __init__(self):
        self.client = mqtt.Client()
        self.event_object = Event()

    def listen_init(self, client, userdata, message):

        received_id = int.from_bytes(message.payload, 'big')
        if received_id not in self.hellos:
            self.hellos.append(received_id)
            self.client.publish('init', self.id)

        if len(self.hellos) == 10 and not self.got_all:
            self.event_object.set()
            self.got_all = True

    def listen_elect(self, client, userdata, message):
        body = json.loads(message.payload)

        if len(self.elections) == 10:
            self.elections = []

        self.elections.append((body['id'], body['election']))

        if len(self.elections) == 10:
            self.event_object.set()
    
    def listen_challenge(self, client, userdata, message):
        body = json.loads(message.payload)

        self.current_challenge = body['challenge']
        self.event_object.set()

    def init(self):
        self.state = 'init'
        self.client.publish('init', self.id)

        self.client.loop_start()
        flag = self.event_object.wait(5)
        if not flag:
            print(f'{self.id}: Timeout waiting for init messages. Exitting...')
            sys.exit()
        self.client.loop_stop()

        self.event_object.clear()

    def elect(self):
        self.state = 'elect'

        body = {
            'election': random.randint(0, 255),
            'id': self.id
        }

        message = json.dumps(body)
        self.client.publish('election', message)

        self.client.loop_start()
        flag = self.event_object.wait(5)
        if not flag:
            print(f'{self.id}: Timeout waiting for elections. Exitting...')
            sys.exit()
        self.client.loop_stop()

        self.event_object.clear()
        elected = sorted(self.elections, key=operator.itemgetter(1, 0))[-1]
        self.current_leader = elected[0]
    
    def challenge(self):
        self.state = 'challenge'

        if self.current_leader == self.id:
            challenge = random.randint(1,120)

            body = {
                'id': self.id,
                'challenge': challenge
            }

            message = json.dumps(body)
            self.client.publish('challenge', message)
            self.current_challenge = challenge
        
            print(f'{self.id}: Current leader. Challenge is {self.current_challenge}')

        else:
            self.client.loop_start()
            flag = self.event_object.wait(5)
            if not flag:
                print(f'{self.id}: Timeout waiting for challenge. Exitting...')
                sys.exit()
            self.client.loop_stop()

            self.event_object.clear()

    def connect(self, broker_address):
        self.id = time.time_ns()
        self.broker_address = broker_address
        self.client.connect(broker_address)
        print(f'{self.id}: Connected to broker')
    
    def run(self):
        print(f'{self.id}: Started transaction mining')

        self.hellos = []
        self.elections = []
        self.current_leader = None
        self.current_challenge = None
        self.init_responses = 0
        self.state = None
        self.got_all = False

        self.client.subscribe('challenge')
        self.client.subscribe('election')
        self.client.subscribe('init')

        self.client.message_callback_add('init', self.listen_init)
        self.client.message_callback_add('election', self.listen_elect)
        self.client.message_callback_add('challenge', self.listen_challenge)

        self.init()
        print(f'{self.id}: Received all init messages')

        self.elect()
        print(f'{self.id}: Received all election messages. Leader is {self.current_leader}')

        self.challenge()
        print(f'{self.id}: Received challenge {self.current_challenge}')
        

elect_chain_peer = ElectChainPeer()
elect_chain_peer.connect('127.0.0.1')
elect_chain_peer.run()
