import config
import logging
import time
import utils
from bitcoinrpc.authproxy import JSONRPCException
from bitcoin.core import lx, b2x, COIN, COutPoint, CMutableTxOut, CMutableTxIn, CMutableTransaction, Hash160
from bitcoin.core.script import CScript, OP_DUP, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG, SignatureHash, SIGHASH_NONE, SIGHASH_ALL, SIGHASH_ANYONECANPAY, SIGHASH_SINGLE
from bitcoin.wallet import CBitcoinAddress
from datetime import datetime


class Event:

    def __init__(self, context):
        self.context = context

    def execute(self):
        utils.check_for_file(config.ticks_csv)
        with open(config.ticks_csv, 'r') as file:

            for line in file.readlines():
                start_time = time.time()

                line = line.rstrip()
                cmds = line.split(';')
                for cmd in cmds:
                    self.execute_cmd(cmd)
                next_tick = start_time + self.context.args.tick_duration
                current_time = time.time()
                if current_time < next_tick:
                    difference = next_tick - current_time
                    logging.info('Sleep {} seconds for next tick.'.format(difference))
                    utils.sleep(difference)
                else:
                    logging.error('Current_time={} is higher then next_tick={}.'
                                  ' Consider to raise the tick_duration which is currently {}s.'
                                  .format(current_time, next_tick, self.context.args.tick_duration))
                    exit(-1)

    def execute_cmd(self, cmd):
        cmd_parts = cmd.split(' ')
        if cmd_parts[0] == 'tx':
            node = self.context.all_bitcoin_nodes[cmd_parts[1]]
            try:
                generate_tx(node)
            except JSONRPCException as exce:
                self.context.tx_exceptions.append(TransactionException(node.name, datetime.now(), exce.message))
                logging.info('Could not generate tx for node {}. Exception={}'.format(node.name, exce.message))
        elif cmd_parts[0] == 'block':
            node = self.context.all_bitcoin_nodes[cmd_parts[1]]
            block_hash = node.execute_rpc('generate', 1)
            logging.info('Created block with hash={}'.format(block_hash))
        elif len(cmd) == 0:
            pass
        else:
            raise Exception('Unknown cmd={} in {}-file'.format(cmd_parts[0], config.ticks_csv))


def generate_tx(node):
    # generate_tx_rpc is not always successful. eg. miner has not enough money or tx fee calculation fails
    tx_chain = node.get_next_tx_chain()
    txid = lx(tx_chain.current_unspent_tx)
    txin = CMutableTxIn(COutPoint(txid, 0))
    txin_scriptPubKey = CScript([OP_DUP, OP_HASH160, Hash160(tx_chain.seckey.pub), OP_EQUALVERIFY, OP_CHECKSIG])

    amount_in = tx_chain.available_coins
    tx_chain.available_coins -= config.smallest_amount + config.transaction_fee
    txout1 = CMutableTxOut(tx_chain.available_coins, CBitcoinAddress(tx_chain.address).to_scriptPubKey())
    txout2 = CMutableTxOut(config.smallest_amount, CBitcoinAddress(node.spent_to_address).to_scriptPubKey())

    tx = CMutableTransaction([txin], [txout1, txout2], nVersion=2)

    sighash = SignatureHash(txin_scriptPubKey, tx, 0, SIGHASH_ALL)
    sig = tx_chain.seckey.sign(sighash) + bytes([SIGHASH_ALL])
    txin.scriptSig = CScript([sig, tx_chain.seckey.pub])

    tx_serialized = tx.serialize()
    logging.info('{} trying to sendrawtransaction (in={}, out={};{} fee={} bytes={}) using tx_chain number={}'
                 .format(node.name, amount_in, txout1.nValue, txout2.nValue,
                         amount_in - (txout1.nValue + txout2.nValue), len(tx_serialized),
                         node.current_tx_chain_index))
    tx_hash = node.execute_rpc('sendrawtransaction', b2x(tx_serialized))
    tx_chain.current_unspent_tx = tx_hash
    logging.info('{} sendrawtransaction (in={}, out={};{} fee={} bytes={}), which got tx_hash={}'
                 .format(node.name, amount_in, txout1.nValue, txout2.nValue,
                         amount_in - (txout1.nValue + txout2.nValue), len(tx_serialized), tx_hash))


class TransactionException:
    def __init__(self, node, timestamp, error_message):
        self.node = node
        self.timestamp = timestamp
        self.error_message = error_message
