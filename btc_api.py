from bitcoinrpc.connection import BitcoinConnection
from bitcoinrpc.exceptions import BitcoinException
from subprocess import Popen
from decimal import Decimal
import atexit
from time import sleep
from socket import error as sock_err
from shutil import rmtree


RPC_UNAME = 'btcapi'
RPC_PWD = 'btcapipwd'


class BTCMgr(object):
    def __init__(self, uname=RPC_UNAME, pwd=RPC_PWD):
        self.connection = BitcoinConnection(uname, pwd, host='127.0.0.1', port=18332)
        self.daemon = Popen(['bitcoind', '-regtest', '-datadir=.', '-rpcuser={0}'.format(uname), '-rpcpassword={0}'.format(pwd)])
        while True:
            try:
                self.get_balance()
                break
            except (sock_err, BitcoinException):
                sleep(0.1)
                continue

        @atexit.register
        def onexit():
            if self.daemon:
                self.daemon.terminate()
                self.daemon = None

    def _test_get_pubkeys(self, amount):
        """
        generates a number of public keys which can be used to test things
        :param amount: number of keys to make
        :return: list of full public keys
        """
        addrs = [self.connection.getnewaddress() for i in xrange(amount)]
        return [addr_info['pubkey'] for addr_info in [self.connection.proxy.validateaddress(addr) for addr in addrs]]

    def make_address(self, account):
        return self.connection.getnewaddress(account)

    def get_balance(self):
        return self.connection.listaccounts(as_dict=True)

    def send_to(self, tx_list):
        for tx in tx_list:
            account, target, amount = tx
            self.connection.sendfrom(account, target, amount)

    def make_multisig(self, min_signs, total_signs, pub_keys, account=''):
        addrs = [self.connection.getnewaddress() for i in xrange(total_signs - len(pub_keys))]
        return self.connection.proxy.addmultisigaddress(min_signs, addrs + pub_keys, account)

    def withdraw_multisig(self, address, fee=Decimal(5e-5)):
        address_info = self.connection.proxy.validateaddress(address)
        account = address_info['account']
        signed_by = address_info['addresses']
        my_signatures = [addr for addr in signed_by if self.connection.proxy.validateaddress(addr)['ismine']]
        withdraw_addr = self.connection.getnewaddress(account)
        UTXOs = self.connection.proxy.listunspent(1, 999999999, [address])

        for UTXO_from_msig in UTXOs:
            txid = UTXO_from_msig['txid']

            rawtx = self.connection.proxy.getrawtransaction(txid, 1)
            for UTXO_vout, vout in enumerate(rawtx['vout']):
                if address in vout['scriptPubKey']['addresses']:
                    break
            UTXO_outscr = vout['scriptPubKey']['hex']
            UTXO_sum = vout['value']
            redeem_script = UTXO_from_msig['redeemScript']
            newtx = self.connection.proxy.createrawtransaction([{'txid': txid, 'vout': UTXO_vout}],
                                                               {withdraw_addr: float(UTXO_sum - fee)})

            privkeys = (self.connection.proxy.dumpprivkey(addr) for addr in
                        my_signatures)
            sign_complete = False
            while not sign_complete:
                privkey = privkeys.next()
                signed = self.connection.proxy.signrawtransaction(newtx, [{'txid': txid, 'vout': UTXO_vout,
                                                                    'scriptPubKey': UTXO_outscr,
                                                                    'redeemScript': redeem_script}],
                                                                    [privkey])
                sign_complete = signed['complete']
                newtx = signed['hex']
            self.connection.proxy.sendrawtransaction(newtx)

    def get_transactions(self):
        return self.connection.proxy.listtransactions()

    def __del__(self):
        if self.daemon:
            self.daemon.terminate()
            self.daemon = None


if __name__ == '__main__':
    rmtree('./regtest', ignore_errors=True)

    m = BTCMgr()

    m.connection.proxy.generate(101)
    addr1 = m.make_address('acc1')
    addr2 = m.make_address('acc2')

    m.send_to([('', addr1, 5.0,),])
    m.connection.proxy.generate(1)
    m.send_to([('acc1', addr2, 2.1,),])
    m.connection.proxy.generate(1)

    msig = m.make_multisig(2, 4, m._test_get_pubkeys(2), 'acc3')

    m.send_to([('acc2', msig, 0.55,),])
    m.connection.proxy.generate(1)

    m.withdraw_multisig(msig)
    m.connection.proxy.generate(1)

    print(m.get_balance())
    print(m.get_transactions())

