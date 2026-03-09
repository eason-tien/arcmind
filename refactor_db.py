import os
import glob

def refactor_file(file_path):
    with open(file_path, "r") as f:
        lines = f.read().splitlines()
    
    from_str = "db = next(get_db())"
    if from_str not in "\n".join(lines):
        return False
        
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if from_str in line:
            indent = line[:len(line) - len(line.lstrip())]
            out.append(line.replace(from_str, "with get_db_session() as db:"))
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() == "":
                    out.append(next_line)
                    i += 1
                    continue
                next_indent = next_line[:len(next_line) - len(next_line.lstrip())]
                if len(next_indent) <= len(indent):
                    # We broke out of the block!
                    break
                out.append("    " + next_line)
                i += 1
            continue
        else:
            out.append(line)
            i += 1
            
    with open(file_path, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"Refactored {file_path}")
    return True

if __name__ == "__main__":
    import sys
    files = sys.argv[1:]
    for f in files:
        refactor_file(f)
