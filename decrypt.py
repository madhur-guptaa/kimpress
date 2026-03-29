"""
Kimpress decompressor.

Usage:
    python decrypt.py <compressed_file>

Reads a Kimpress-compressed file and writes the decompressed output to stdout.
"""

import sys
import re

# Parsing helpers

# This regex matches a double-quoted string and captures everything inside.
# It handles escaped characters (like \" or \\) so they don't prematurely
# terminate the string or break the logic.
QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def parse_quoted(token: str) -> str:
    """
    Extract the content of a double-quoted string and interpret escape
    sequences so that:
        \\n  →  newline
        \\\\  →  single backslash
        \\"  →  double quote
    Any other backslash sequence is passed through unchanged.
    """
    # Use the pre-compiled regex to validate the format and extract the inner content
    m = QUOTED_RE.fullmatch(token)
    if m is None:
        raise ValueError(f"Expected a quoted string, got: {token!r}")

    # m.group(1) contains the string content excluding the surrounding double quotes
    raw = m.group(1)

    result = []
    i = 0
    # Iterate through the raw string character by character
    while i < len(raw):
        # Check for a backslash that is not at the very end of the string
        if raw[i] == "\\" and i + 1 < len(raw):
            next_ch = raw[i + 1]

            # Lookahead: handle recognized escape sequences
            if next_ch == "n":
                result.append("\n")  # Convert \n to a literal newline
            elif next_ch == "\\":
                result.append("\\")  # Convert \\ to a literal backslash
            elif next_ch == '"':
                result.append('"')  # Convert \" to a literal double quote
            else:
                # Sequence not recognized: preserve both the backslash and the char
                result.append("\\")
                result.append(next_ch)

            # Skip the character we just looked ahead at
            i += 2

        # Regular character: append as-is and move to the next index
        else:
            result.append(raw[i])
            i += 1

    return "".join(result)


def parse_int(token: str) -> int:
    try:
        return int(token)
    except ValueError:
        # Handle cases of non-int token
        raise ValueError(f"Expected an integer, got: {token!r}")


def parse_instruction(line: str):
    """
    Parse one line of a Kimpress compressed file into a (opcode, args) tuple.
    Returns one of:
        ("LIT",  text)
        ("RLE",  count, text)
        ("REF",  [line_number, ...])
    Raises ValueError for malformed lines.
    """
    # Split the instruction to get the opcode and the remainder.
    # Keep whitespace so quoted strings with internal spaces survive intact.
    parts = line.split(None, 1)
    if not parts:
        # Handle cases where line is empty
        raise ValueError("Empty instruction line")

    # Handling operation code case insensitivity
    opcode = parts[0].upper()
    string = parts[1] if len(parts) > 1 else ""

    # LIT - Output should be the specified literal string within quotes.
    if opcode == "LIT":
        # Format: LIT "<text>"
        # Parse the string and remove trailing whitespaces
        return "LIT", parse_quoted(string.strip())

    # RLE - Run Length Encoding: Replicate the string within quotes the specified number of times.
    elif opcode == "RLE":
        # Format: RLE <count> "<text>"
        # Split the string to get the replication number and replication string
        rle_parts = string.split(None, 1)
        if len(rle_parts) != 2:
            # Handle cases where <count> or <text> is empty
            raise ValueError(f"RLE expects <count> \"<text>\", got: {string!r}")
        # Parse the int
        count = parse_int(rle_parts[0])
        # Parse the string and remove trailing whitespaces
        text = parse_quoted(rle_parts[1].strip())
        return "RLE", count, text

    # REF - Output the result from the specified lines (indices are 1-based).
    elif opcode == "REF":
        # Format: REF <n1> [n2 ...]  (one or more 1-based line indices)
        # Get all line numbers of instructions that need to be repeated
        indices = [parse_int(t) for t in string.split()]
        if not indices:
            # Handle cases where no line number is present
            raise ValueError("REF requires at least one line index")
        return "REF", indices

    else:
        # Handle cases where unknown operation code is present
        raise ValueError(f"Unknown opcode: {opcode!r}")


# Kimpress Decompressor
def decompress(compressed_path: str, out) -> None:
    """
    Decompress given file and print to console. Each instruction's output is
    stored so that REF can reference it later. Because the total output may
    be large we only keep per-instruction strings in memory (which are individually
    small) and stream everything else.
    """
    # Load and parse all instructions up front.
    # Compressed files have at most a few thousand lines, so
    # this is fine and allows forward REF resolution.
    instructions = []
    with open(compressed_path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.rstrip("\n")
            if not line:
                # Skip blank lines
                continue
            try:
                # Parse instruction and then store it
                parsed = parse_instruction(line)
                instructions.append(parsed)
            # Handle cases where non-standard instruction is present
            except ValueError as exc:
                raise ValueError(f"Parse error on line {lineno}: {exc}") from exc

    # Cache to store already-computed instruction outputs.
    # Each entry is a list of string chunks produced by that instruction.
    cache = {}

    def execute(idx: int, stack=None):
        # Initialize the recursion stack to track visited lines and prevent infinite loops
        if stack is None:
            stack = set()

        # Detect if a line refers back to itself or an active caller (circular reference)
        if idx in stack:
            raise ValueError(f"Circular REF detected involving line {idx + 1}")

        # Check if this line's output has already been computed and cached
        if idx in cache:
            yield from cache[idx]
            return

        # Mark this index as "active" before descending into deeper references
        stack.add(idx)

        instr = instructions[idx]
        opcode = instr[0]

        chunks = []

        # LIT: just yield the literal text directly
        if opcode == "LIT":
            chunks.append(instr[1])

        # RLE: repeat a string 'count' times
        elif opcode == "RLE":
            _, count, text = instr
            for _ in range(count):
                chunks.append(text)

        # REF: fetch content from other line indices (1-based in input)
        elif opcode == "REF":
            _, indices = instr
            for ref_1based in indices:
                ref_idx = ref_1based - 1  # Convert 1-based index to 0-based

                # Bounds checking for safety
                if ref_idx < 0 or ref_idx >= len(instructions):
                    raise ValueError(
                        f"REF index {ref_1based} is out of range "
                        f"(file has {len(instructions)} instructions)"
                    )

                # Recursively resolve the referenced line and collect its chunks
                chunks.extend(execute(ref_idx, stack))

        # Store the fully-realized output so future REF calls can reuse it cheaply.
        # Using a list (not a generator) ensures the cache is never exhausted on
        # repeated access.
        cache[idx] = chunks

        yield from chunks

        # "Un-mark" the index as we bubble back up the recursion tree
        stack.remove(idx)

    # Execute every instruction in order and stream output.
    for i in range(len(instructions)):
        for chunk in execute(i):
            out.write(chunk)


# Entry point to decompressor
def main():
    # Ensure exactly one command-line argument is provided (the filename)
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} <compressed_file>", file=sys.stderr)
        sys.exit(1)

    compressed_path = sys.argv[1]

    # Attempt to decompress the file and stream the output to the console
    try:
        decompress(compressed_path, sys.stdout)
    # Handle cases where the input path does not exist
    except FileNotFoundError:
        print(f"Error: file not found: {compressed_path!r}", file=sys.stderr)
        sys.exit(1)
    # Handle malformed data or decompression-specific errors
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
