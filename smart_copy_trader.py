# Complete Fixed Smart Copy Trader Code

# Import necessary libraries
import threading
import time
import random

class SmartCopyTrader:
    def __init__(self, trader_id):
        self.trader_id = trader_id
        self.lead_snapshot = []
        self.symbol_order = []
        self.lock = threading.Lock()

    def fetch_lead_snapshot(self):
        # Simulate fetching lead snapshot
        self.lead_snapshot = list(range(1, 6))  # Sample data
        print(f"Lead snapshot for trader {self.trader_id}: {self.lead_snapshot}")

    def trade(self):
        # Simulate trading functionality
        with self.lock:
            if not self.lead_snapshot:
                print(f"Trader {self.trader_id} has an empty lead snapshot!")
                return
            print(f"Trader {self.trader_id} is trading with snapshot: {self.lead_snapshot}")

    def run(self):
        self.fetch_lead_snapshot()
        self.trade()

# Main function to start trading threads
def start_trading():
    traders = [SmartCopyTrader(i) for i in range(3)]
    threads = []
    for trader in traders:
        thread = threading.Thread(target=trader.run)
        threads.append(thread)
        thread.start()
        time.sleep(random.random())  # Random sleep to simulate staggered starts

    for thread in threads:
        thread.join()

if __name__ == "__main__":
    start_trading()