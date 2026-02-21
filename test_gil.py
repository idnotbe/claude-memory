import urllib.request
import concurrent.futures
import time

def fetch_url(url):
    try:
        urllib.request.urlopen(url, timeout=5).read()
    except Exception as e:
        pass # don't care about the content, just the network block
        
urls = ['http://example.com', 'http://example.org']

# Sequential
start = time.time()
for u in urls:
    fetch_url(u)
seq_time = time.time() - start
print(f"Sequential: {seq_time:.2f}s")

# Parallel
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    executor.map(fetch_url, urls)
par_time = time.time() - start
print(f"Parallel: {par_time:.2f}s")
