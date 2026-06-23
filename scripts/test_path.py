import sys
print("Empty string in path:", '' in sys.path)
print("CWD in path:", __import__('os').getcwd() in sys.path)
