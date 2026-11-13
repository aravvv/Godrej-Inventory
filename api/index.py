import sys
import os

# Ensure the root project directory is in the Python module search path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
