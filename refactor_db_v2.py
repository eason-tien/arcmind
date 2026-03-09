import sys

def refactor_file(file_path):
    with open(file_path, "r") as f:
        lines = f.read().splitlines()
        
    out = []
    active_blocks = []
    
    for line in lines:
        if line.strip() == "":
            out.append(line)
            continue
            
        current_orig_indent = len(line) - len(line.lstrip())
        
        # Pop blocks that we have exited
        while active_blocks and current_orig_indent <= active_blocks[-1]:
            # Wait, if current_orig_indent <= active_blocks[-1]:
            # If current_orig_indent == active_blocks[-1], it means we are at the SAME level
            # as the original `db = next()` line.
            # But wait! The lines that follow `db = next()` inside the SAME block
            # ALSO have `current_orig_indent == active_blocks[-1]` !
            # E.g.:
            # db = next(get_db())   <-- orig=8
            # db.add(x)             <-- orig=8
            # If we pop when orig <= 8, we will POP immediately and `db.add` won't be indented!
            # So we MUST ONLY pop when `current_orig_indent < active_blocks[-1]`!
            if current_orig_indent < active_blocks[-1]:
                active_blocks.pop()
            else:
                break
            
        extra_indent = " " * (4 * len(active_blocks))
        
        if "db = next(get_db())" in line:
            new_line = extra_indent + line
            new_line = new_line.replace("db = next(get_db())", "with get_db_session() as db:")
            out.append(new_line)
            
            active_blocks.append(current_orig_indent)
        else:
            out.append(extra_indent + line)
            
    with open(file_path, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"Refactored {file_path}")

for f in sys.argv[1:]:
    refactor_file(f)
