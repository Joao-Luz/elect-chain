import paho.mqtt.client as mqtt
import time

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

    def init(self):
        self.client.loop_start()
        while len(self.hellos) < 10:
            self.client.publish('init', self.id)
            self.client.subscribe('init')
            time.sleep(1)
        self.client.loop_stop()

    def connect(self, broker_address):
        self.broker_address = broker_address
        self.client.connect(broker_address)

        print(f'I\'m peer {self.id} and i\'m connected!')

        self.client.subscribe('election')
        self.client.subscribe('challenge')

        self.hellos = []
        self.init_responses = 0
        self.state = 'init'
        self.got_all = False

        self.client.message_callback_add('init', self.listen_init)
        self.client.loop_start()

        self.init()
 
    
    def loop(self):
        self.client.loop_forever()

elect_chain_peer = ElectChainPeer()
elect_chain_peer.connect('127.0.0.1')