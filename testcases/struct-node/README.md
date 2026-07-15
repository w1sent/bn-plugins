# struct-node

Test binary for `ai/suggest-structs`. Exercises all three suggest-structs
triggers with obvious, hand-designed shapes:

- `alloc_node()`'s heap pointer `p` -- accessed via raw offset math
  (`p+0`, `p+4`, `p+8`, `p+24`) with no struct ever declared in source.
  Trigger 1 (variable access-pattern analysis) should recover something
  close to `{ int id; int name_len; char name[16]; void* next; }`.
- `g_config` -- a named 16-byte global blob, for manually testing trigger 2
  (selection -> byte-range seed) by selecting its bytes in BN and running
  "Suggest Struct (Selection)".
- an 8-byte blob whose symbol (`g_scratch` in source) is stripped by
  `build.py`, so Binary Ninja names it `data_<addr>` -- the auto-generated
  name pattern trigger 3's batch sweep looks for.

## Build

```
python build.py
```

Requires a C compiler (gcc/clang); `objcopy` (binutils) is used to strip
`g_scratch`'s symbol but is optional -- see `python build.py requirements`.

## Use

See `ai/suggest-structs/tests/run.py` for a script that loads `node.bin`
and drives the plugin's `api.py` directly (run via Binary Ninja's
Tools > Run Script). You can also just open `node.bin` in Binary Ninja and
run the "Suggest Struct" / "Suggest Struct (Selection)" / "Suggest Struct
(Batch)" commands manually against it.
