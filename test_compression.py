"""Test memory compression directly."""
import db.engine as _eng
_eng._engine = None

from core.memory.compression import MemoryCompressor

compressor = MemoryCompressor("empire-alpha")

print("=== Stats before ===")
stats = compressor.get_compression_stats()
print(f"Total: {stats['total_memories']}, Compressed: {stats['compressed_summaries']}, Compressible: {stats['compressible_now']}")

print()
print("=== Compress by topic: transformer ===")
result = compressor.compress_by_topic("transformer")
if result:
    print(f"Title: {result['title']}")
    print(f"Memories compressed: {result['memories_compressed']}")
    print(f"Summary words: {result['summary_words']}")
    print(f"Cost: ${result['cost']:.4f}")
else:
    print("Not enough memories to compress (need 3+)")

print()
print("=== Stats after ===")
stats = compressor.get_compression_stats()
print(f"Total: {stats['total_memories']}, Compressed: {stats['compressed_summaries']}, Archived: {stats['archived_originals']}")
