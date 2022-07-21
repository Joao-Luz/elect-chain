# elect-chain

This is yet another simple implementation that tries to mimic the block chain concept. This time, the system uses the [Mosquitto Broker](https://mosquitto.org/) to act as a medium for the communication of peers without a central server.

## How it works

The system is composed of a single peer program that knows how to communicate with other peers.

At the start of the process, all clients wait untill there are 10 people present in the system. They know about each others' presence by sending a message to the broker containing their respective id's for the session (i.e. a timestamp of the moment they connected to the broker).

After that, all peers elect a leader, who will be responsible for generating and distributing the challenge. The leader is chosen as all peers send a message to the broker with a random number. With that, every participant selects a leader as the one with the highest random number, with the timestamp id acting as a tiebreaker.

After the leader selects a random challenge and makes it public for all peers via broker, the participants must do the minig task and publish a valid seed as soon as possible. When submitting a seed, all peers must vote wether it is valid or not. If the majority of the members vote 'yes', the respective participant wins the transaction.

This process runs in a loop. Every iteration, the challenge changes, although the leader stays the same.

## Specifications

### Values

- `id`: The id of a user in the system. Represented by a 64-bit unix timestamp.

### Topics
The topics (or channels) used for the implementation, along with their respective message formats are:

- `init`: The channel where users must submit their ids to enter the system. Example:
```py
    {
        id: 1658115562918731603 # The timestamp id
    }
```
- `election`: The channel where users must submit random values in order to be selected as the leader. Example:
```py
    {
        id: 1658115562918731603, # The timestamp id
        election: 165            # A random value between 0 and 255
    }
```
- `challenge`: Where the leader must publish the challenge. Example:
```py
    {
        id: 1658115562918731603, # The timestamp id
        challenge: 34            # A random value between 1 and 120
    }
```
- `solution`: Where users must publish their solution. Example:
```py
    {
        id: 1658115562918731603, # The timestamp id
        transaction: 16,         # The respective transaction id
        solution: 235470176      # The integer that solves the challenge
    }
```
- `voting`: Where users must publish their vote. Example:
```py
    {
        id: 1658115562918731603, # The timestamp id
        transaction: 16,         # The respective transaction id
        seed: 235470176          # The seed being voted
        vote: False              # The vote. Yes - True, No - False
    }
```
### Execution flow

These are the main states of the program and what happens inside each of them:

1. **Initialization**: The peer connects to the broker and sends its `id`. It must, then, wait for all 10 unique messages (including its own) to jump to the next step;

2. **Election**: The users send a random value between 0 and 255 via broker to other users. Each user gets the one with the biggest value (and smallest id timestamp as a tiebreaker) as the leader;

3. **Challenge**: The leader must generate a random challenge with a value between 1 and 120. It then publishes on the broker, where remaining users are waiting for the challenge message;

4. **Runnig**: The peer spawns 2 threads. The first waits for solutions from other users and validates them. If the seed is not valid, send a voting message and keep waiting for a valid one. Else, must stop the other thread and proceed to voting.

    The second thread tries to find a solution to the challenge and, when one is found, publishes to the broker and goes to voting. This thread also spaws n processes to perform a parallel mining of the seed, with n being the number of available cores.

5. **Voting**: All users must wait for everyone's vote for the current solution. If the majority (i.e., at least 6 people) vote yes, all peers update the internal table containing the transactions and returns to a new challenge. Else, return to the `running` process.

## Usage

To run an instance of the peer, do:

    $ python peer.py [broker_address]

There is also a testing script `launch_clients.sh` that will launch the required 10 instances and run the system locally.

## Explanation video

[Link](https://drive.google.com/drive/folders/1zMRrRYSwVeAVy3M_LxpoIxHzpycjTLX7?usp=sharing)
