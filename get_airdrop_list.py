import json
from web3 import Web3
import sys
import warnings

if not sys.warnoptions:
    warnings.simplefilter("ignore")

w3 = Web3(Web3.HTTPProvider('https://smartbch.fountainhead.cash/mainnet'))
target_token_address = w3.toChecksumAddress(
    "0x3d13DaFcCA3a188DB340c81414239Bc2be312Ec9")  # In this case, AxieBCH address
ignored_addresses = []  # For example, admin wallet. The program will addresses usually related to allowance.
address_list = []
balances = {}
amount_to_share = 1  # Amount of tokens or BCH to be airdropped.
airdrop_threshold = 10  # Amount of tokens one address must hold the get an airdrop.
LP_CA_list = []  # Liquidity pools address list will be added by the app, you can add manually if anyone is missing.
lp_factories = {"benswap": {"address": "0x8d973bAD782c1FFfd8FcC9d7579542BA7Dd0998D", "start_block": 295042},
                "mist": {"address": "0x6008247F53395E7be698249770aa1D2bfE265Ca0", "start_block": 989302},
                "muesliswap": {"address": "0x72cd8c0B5169Ff1f337E2b8F5b121f8510b52117", "start_block": 770000}} # Factories for every DEX

createPair_topic = ["0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"]

def get_liquidity_pools():
    ABI = open("UniswapV2Factory.json", "r")  # Standard ABI for LP factories
    abi = json.loads(ABI.read())
    for factory in lp_factories:
        factory_contract = w3.eth.contract(address=lp_factories[factory]["address"], abi=abi)
        logs = w3.eth.get_logs({'topic': createPair_topic, 'address': lp_factories[factory]["address"],
                                'fromBlock': lp_factories[factory]["start_block"]})
        for i in range(len(logs)):
            tx_hash = logs[i].transactionHash
            receipt = w3.eth.getTransactionReceipt(tx_hash)
            pair = factory_contract.events.PairCreated().processReceipt(receipt)
            if pair[0].args.token0 == target_token_address or pair[0].args.token1 == target_token_address:
                LP_CA_list.append(pair[0].args.pair)

def get_LPs_info(LP_CA_list, target_token_address):
    ABI = open("UniswapV2Pair.json", "r")  # Standard ABI for LP tokens
    abi = json.loads(ABI.read())
    LPs_dict = {}

    for LP in LP_CA_list:
        contract = w3.eth.contract(address=w3.toChecksumAddress(LP), abi=abi)
        target_token_position = 0
        target_token_reserves = 0
        if contract.functions.token1().call() == target_token_address:
            target_token_position = 1
        if target_token_position == 0:
            target_token_reserves = contract.functions.getReserves().call()[0]
        if target_token_position == 1:
            target_token_reserves = contract.functions.getReserves().call()[1]
        LPs_dict[LP] = {
            "total_supply": contract.functions.totalSupply().call(),
            "decimals": contract.functions.decimals().call(),
            "target_token_position": target_token_position,
            "target_token_reserve": target_token_reserves
        }
    return LPs_dict


def address_tracker(data):
    addresses_owning_LPs = {k: [] for k in LP_CA_list}  # Dictionary containing LP_address:[owners list] elements
    for block_number in data["blocks"]:
        for txhash in data["blocks"][block_number]:
            for tx in data["blocks"][block_number][txhash]:
                if data["blocks"][block_number][txhash][tx]["to"] not in address_list:
                    address_list.append(data["blocks"][block_number][txhash][tx]["to"])
                if data["blocks"][block_number][txhash][tx]["from"] not in address_list and \
                        data["blocks"][block_number][txhash][tx]["from"] not in ignored_addresses:
                    ignored_addresses.append(data["blocks"][block_number][txhash][tx]["from"])
                if data["blocks"][block_number][txhash][tx]["to"] in addresses_owning_LPs.keys():
                    if data["blocks"][block_number][txhash][tx]["from"] not in addresses_owning_LPs[
                        data["blocks"][block_number][txhash][tx]["to"]]:
                        addresses_owning_LPs[data["blocks"][block_number][txhash][tx]["to"]].append(
                            data["blocks"][block_number][txhash][tx]["from"])  # Keeps track of addresses owning LPs

    for LP in LP_CA_list:
        address_list.remove(w3.toChecksumAddress(LP))  # We delete balances hold in LP tokens


    for address in ignored_addresses:
        if address in address_list:
            address_list.remove(address)

    return addresses_owning_LPs

def get_LP_balances(addresses_owning_LPs, LPs_dict):
    for LP_address in addresses_owning_LPs:
        ABI = open("UniswapV2Pair.json", "r")  # Standard ABI for LP tokens
        abi = json.loads(ABI.read())
        contract = w3.eth.contract(address=LP_address, abi=abi)
        for address in addresses_owning_LPs[LP_address]:
            address_LP_balance = contract.functions.balanceOf(w3.toChecksumAddress(address)).call()
            if address_LP_balance != 0 and address not in ignored_addresses:
                balances[address] = (address_LP_balance / LPs_dict[LP_address]["total_supply"]) * LPs_dict[LP_address][
                    "target_token_reserve"]


def get_balances(airdrop_threshold):
    total_token_amount: int = 0
    ABI = open("ERC20-ABI.json", "r")  # Standard ABI for ERC20 tokens
    abi = json.loads(ABI.read())
    contract = w3.eth.contract(address=target_token_address, abi=abi)
    decimals = contract.functions.decimals().call()
    airdrop_threshold = airdrop_threshold * 10 ** decimals
    for address in address_list:
        balance = contract.functions.balanceOf(address).call()
        if address in balances: # In this case, the address holds tokens in LP contract
            balances[address] += balance  # Add balance from the LP tokens
            if balances[address] >= airdrop_threshold:
                total_token_amount += balances[address]
            else:
                balances.pop(address)
        else:
            if balance >= airdrop_threshold:
                balances[address] = balance
                total_token_amount += balance

    return total_token_amount

def airdrop_list(balances, amount_to_share, total_token_amount):
    airdrop = {}
    airdrop_list_file = open('airdrop_list.txt', 'w')
    for address in balances:
        airdrop[address] = (balances[address] / total_token_amount) * amount_to_share
        print("{} "" {:.8f}".format(address, airdrop[address]), file=airdrop_list_file)
    airdrop_list_file.close()
    print("Done, airdrop list available in airdrop_list.txt")

def main():
    try:
        file = open("transfer_events.json", "r")
        transfer_data = json.load(file)
    except FileNotFoundError:
        print("File with contract events doesn't exist")
    print("Getting liquidity pools for your token, this may take a while")
    get_liquidity_pools()
    print("Just for your information, these are the liquidity pools for yout token:")
    print(LP_CA_list)
    print("Now getting all balances, please be patient")
    LPs_dict = get_LPs_info(LP_CA_list, target_token_address)
    addresses_owning_LPs = address_tracker(transfer_data)
    get_LP_balances(addresses_owning_LPs, LPs_dict)
    total_token_amount = get_balances(airdrop_threshold)
    print("Making the airdrop list")
    airdrop_list(balances, amount_to_share, total_token_amount)

if __name__== "__main__":
    main()