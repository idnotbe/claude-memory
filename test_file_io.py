import time
import os

# Create 500 small files
os.makedirs('dummy_json', exist_ok=True)
for i in range(500):
    with open(f'dummy_json/doc_{i}.json', 'w') as f:
        f.write('{"title": "Test ' + str(i) + '", "body": "' + 'a'*2000 + '"}')

# Benchmark reading 500 files
start = time.perf_counter()
for i in range(500):
    with open(f'dummy_json/doc_{i}.json', 'r') as f:
        content = f.read()
end = time.perf_counter()

print(f"Reading 500 small files took: {(end - start) * 1000:.2f} ms")

# Cleanup
import shutil
shutil.rmtree('dummy_json')
