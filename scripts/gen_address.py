import argparse
import logging
import multiprocessing
import os
import sys
import time
from pathlib import Path
from queue import Empty

from eth_account import Account


def search_worker(
    prefixes: list[str],
    found_count: multiprocessing.Value,
    n_results: int,
    result_queue: multiprocessing.Queue,
    progress_queue: multiprocessing.Queue,
    batch_size: int = 1000,
    lock: multiprocessing.Lock = None,
) -> None:
    """Worker process that searches for vanity addresses matching given prefixes."""
    try:
        prefixes = [p.lower().replace("0x", "") for p in prefixes]

        while True:
            with lock:
                if found_count.value >= n_results:
                    return

            for _ in range(batch_size):
                account = Account.create()
                address = account.address.lower()

                for prefix in prefixes:
                    if address[2:].startswith(prefix):
                        with lock:
                            if found_count.value < n_results:
                                found_count.value += 1
                                result_queue.put((prefix, account.address, account.key.hex()))

                                if found_count.value >= n_results:
                                    return

            progress_queue.put(batch_size)

    except Exception as e:
        logging.error(f"Worker error: {str(e)}")
        result_queue.put(("ERROR", str(e), None))


def generate_n_vanity_addresses(prefixes: list[str], n: int = 3, timeout: float = 3600) -> list[tuple[str, str, str]]:
    """Generate N Ethereum vanity addresses matching given prefixes."""
    if not prefixes:
        raise ValueError("No prefixes provided")
    if any(len(p) > 40 for p in prefixes):
        raise ValueError("Prefix length cannot exceed 40 characters")

    manager = multiprocessing.Manager()
    found_count = manager.Value("i", 0)
    result_queue = manager.Queue()
    progress_queue = manager.Queue()
    lock = manager.Lock()

    cpu_count = os.cpu_count()
    logging.info(f"Launching {cpu_count} worker processes to find {n} matches...")

    start_time = time.time()
    total_attempts = 0
    results = []

    workers = []
    try:
        for _ in range(cpu_count):
            worker = multiprocessing.Process(
                target=search_worker,
                args=(prefixes, found_count, n, result_queue, progress_queue, 1000, lock),
            )
            worker.start()
            workers.append(worker)

        while len(results) < n:
            try:
                prefix, address, priv_key = result_queue.get(timeout=1)
                if prefix == "ERROR":
                    raise RuntimeError(f"Worker error: {address}")

                elapsed = time.time() - start_time
                idx = len(results) + 1
                print(
                    f"[{idx}/{n}] Found match → Prefix: '{prefix}' | Address: {address} | "
                    f"Private Key: {priv_key} | Time: {elapsed:.2f}s"
                )
                results.append((prefix, address, priv_key))

            except Empty:
                while not progress_queue.empty():
                    total_attempts += progress_queue.get()

                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Search timed out after {timeout} seconds") from None

                logging.info(f"Searched {total_attempts:,} addresses...")

        return results

    finally:
        for worker in workers:
            worker.terminate()
            worker.join()


def generate_random_addresses(n: int) -> list[tuple[str, str]]:
    """Generate N completely random Ethereum addresses."""
    results = []
    for i in range(n):
        acct = Account.create()
        print(f"[{i + 1}/{n}] Address: {acct.address} | Private Key: {acct.key.hex()}")
        results.append((acct.address, acct.key.hex()))
    return results


def persist_results(results: list[tuple[str, str, str]] | list[tuple[str, str]], mode: str) -> None:
    """Append results to a timestamped file under scripts/generated/. Does not overwrite existing files."""
    out_dir = Path(__file__).resolve().parent / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    filename = out_dir / f"{mode}_{timestamp}.txt"

    lines = []
    if mode == "vanity":
        for prefix, addr, key in results:
            lines.append(f"prefix={prefix} address={addr} private_key={key}")
    else:
        for addr, key in results:  # type: ignore[misc]
            lines.append(f"address={addr} private_key={key}")

    with open(filename, "x", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSaved results to {filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate random or vanity Ethereum addresses.")
    parser.add_argument(
        "--mode",
        choices=["random", "vanity"],
        default="random",
        help="Generation mode: random addresses or vanity prefixes.",
    )
    parser.add_argument("--count", "-n", type=int, default=3, help="Number of addresses to generate.")
    parser.add_argument(
        "--prefix",
        action="append",
        default=[],
        help="Vanity prefix to search for (can be passed multiple times). Ignored in random mode.",
    )
    parser.add_argument("--timeout", type=float, default=3600, help="Timeout (seconds) for vanity search.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        if args.mode == "vanity":
            prefixes = args.prefix or ["eth"]
            logging.info("Searching for vanity addresses...")
            results = generate_n_vanity_addresses(prefixes, n=args.count, timeout=args.timeout)

            print("\n=== Summary of Generated Vanity Addresses ===")
            for i, (prefix, addr, key) in enumerate(results, 1):
                print(f"[{i}] prefix={prefix} | address={addr} | private_key={key}")
            persist_results(results, mode="vanity")
        else:
            print(f"Generating {args.count} random Ethereum addresses...")
            results = generate_random_addresses(args.count)

            print("\n=== Summary of Generated Random Addresses ===")
            for i, (addr, key) in enumerate(results, 1):
                print(f"[{i}] address={addr} | private_key=0x{key}")
            persist_results(results, mode="random")
        return 0

    except (ValueError, TimeoutError, RuntimeError) as e:
        logging.error("Error: %s", str(e))
        return 1
    except KeyboardInterrupt:
        logging.info("Search cancelled by user")
        return 1


if __name__ == "__main__":
    sys.exit(main())
