# Kimpress Decompressor

Decompresses files produced by the Kimpress compression scheme.

---

## Requirements

Python 3.9 or later. No third-party packages are needed.

---

## Running the program

```
python3 decrypt.py <compressed_file>
```

Output is written to stdout. To save to a file:

```
python3 decrypt.py compressed.kp > original.txt
```

---

## How Kimpress files work

Each non-blank line in a compressed file is one instruction. Opcodes are
case-insensitive. Three opcodes are supported:

| Opcode | Syntax | Effect |
|--------|--------|--------|
| `LIT` | `LIT "<text>"` | Emit `<text>` verbatim. |
| `RLE` | `RLE <n> "<text>"` | Emit `<text>` repeated `n` times. |
| `REF` | `REF <n1> [n2 …]` | Emit the output of instruction(s) at the given 1-based line numbers (in order). |

### Escape sequences inside quoted strings

| Written in file | Decoded as |
|-----------------|------------|
| `\n` | newline |
| `\\` | single backslash `\` |
| `\"` | double quote `"` |

---

## Design notes & assumptions

### Memory
The problem states that the *output* may be too large to hold in memory.
The decompressor holds only the per-instruction output strings in memory
(each of which is individually small) and streams every character to stdout
as soon as its instruction is executed.  Truly huge outputs (e.g. from a
deeply nested REF chain) would still require the intermediate strings, but
that is unavoidable given the REF back-reference model.

### Forward references
The spec does not explicitly forbid `REF` pointing to a later instruction.
The implementation supports forward references by lazily computing and caching
each instruction's output on first access.

### Self-references / cycles
A `REF` that directly or indirectly references itself would loop forever.
Direct self-reference (a line referencing its own line number) is detected and
raises a clear error.  Indirect cycles are also detected.

### Blank lines
Blank lines in the compressed file are silently skipped.

### `REF` line numbering
Line numbers in `REF` are 1-based indices into the list of *non-blank*
instructions, consistent with the examples provided.

### Verifying the examples

**Example 1** — save the compressed content to `test_case2.txt` and run:

```
python3 decrypt.py test_case2.txt
```

Expected output: `10 7 3 21 21 21 8 21 21 21 8`

**Example 2** — save the compressed content to `test_case1.txt` and run:

```
python3 decrypt.py test_case1.txt
```

Expected output matches the multi-line original shown in the problem statement.