import sys

def fix_indent(file_path):
    with open(file_path, "r") as f:
        lines = f.read().splitlines()
        
    out = []
    i = 0
    in_block_indent = -1
    
    while i < len(lines):
        line = lines[i]
        
        if "with get_db_session() as db:" in line:
            out.append(line)
            # The indent of the 'with' statement
            base_indent_str = line[:len(line) - len(line.lstrip())]
            base_indent = len(base_indent_str)
            
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() == "":
                    # Empty line keeps its original string
                    out.append(next_line)
                    i += 1
                    continue
                
                # Check indent of the next line
                next_indent_str = next_line[:len(next_line) - len(next_line.lstrip())]
                next_indent = len(next_indent_str)
                
                # If the line is at the exact same or less indentation as the `with` statement,
                # we have exited the block that was originally following `db = next(get_db())`.
                # HOWEVER, wait! If `db = next(get_db())` was the last statement in a block, 
                # the original code might have stepped out of the block.
                # In python, `db = next()` is usually followed by code AT THE SAME INDENT level.
                # So if `next_indent <= base_indent`, wait, no!
                # If `next_indent == base_indent`, that IS the code that needs to be indented by 4 spaces!
                # Because it was originally at the same level as `db = next()`.
                # When does the block end?
                # The block ends when it hits a `def `, `return`, or the indentation is STRICTLY LESS than `base_indent`.
                # BUT wait. `return` might be part of the block!
                # Actually, the block should contain all lines until the indentation is STRICTLY LESS than `base_indent`.
                # EXCEPT if it's the start of a new `def ` or `class `, which means we exited the block too.
                if next_indent < base_indent:
                    break
                    
                if next_indent == base_indent:
                    # Is it a new block like `except`, `finally`, `elif`, `else`?
                    # If `db = next()` was inside a `try`, then the block ends at `except` or `finally`.
                    if next_line.lstrip().startswith(("except ", "except:", "finally:", "elif ", "else:")):
                        break
                        
                # Add 4 spaces
                out.append("    " + next_line)
                i += 1
                
            continue
            
        else:
            out.append(line)
            i += 1
            
    with open(file_path, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"Fixed {file_path}")

files = sys.argv[1:]
for f in files:
    fix_indent(f)
