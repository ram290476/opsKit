# Topic: P24. Valid Parentheses / Stack-based Config Validation
# Section: 10. Hashmap & Stack Fundamentals
# Source: /workspace/interview_prep/Data_Structures_Interview_Questions_Platform_SRE.docx
# (Code below is copied verbatim from the document.)

PAIRS = {")": "(", "]": "[", "}": "{"}
 
def is_valid(s):
    stack = []
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in PAIRS:
            if not stack or stack.pop() != PAIRS[ch]:
                return False
    return not stack
 
def find_bracket_error(text):
    """None, or (line, col, message)."""
    stack, in_str = [], None
    for ln, line in enumerate(text.splitlines(), 1):
        for col, ch in enumerate(line, 1):
            if in_str:
                if ch == in_str:
                    in_str = None
            elif ch in "\"'":
                in_str = ch
            elif ch in "([{":
                stack.append((ch, ln, col))
            elif ch in PAIRS:
                if not stack or stack[-1][0] != PAIRS[ch]:
                    return (ln, col, f"unexpected {ch!r}")
                stack.pop()
    if stack:
        ch, ln, col = stack[-1]
        return (ln, col, f"unclosed {ch!r}")
    return None
 
assert is_valid("{[()]}") and not is_valid("(]")
assert not is_valid("((") and is_valid("")
good = '{\n  "cmd": ["echo", "}"]\n}'
assert find_bracket_error(good) is None
assert find_bracket_error('{\n  "a": [1, 2}\n') == \
    (2, 13, "unexpected '}'")
assert find_bracket_error('{"a": 1') == \
    (1, 1, "unclosed '{'")
