import sys
import argparse
from cli import DataManagerCLI
from logger import setup_logger

def main():
    setup_logger()
    parser = argparse.ArgumentParser(description="DataManager Command Line Interface")
    parser.add_argument('-i', '--interactive', action='store_true', help="Start in interactive mode")
    # Capture extra arguments that compose the native command without triggering an error
    parser.add_argument('command', nargs=argparse.REMAINDER, help="Direct command for execution")
    
    args = parser.parse_args()

    try:
        cli = DataManagerCLI()
        
        if args.interactive:
            # Run continuous shell
            cli.cmdloop()
        elif args.command:
            # Command arrived as an argument without the -i flag
            # Join everything as a string and pass it to the native cmd to interpret
            cmd_str = " ".join(args.command)
            # Disable intro banner
            cli.onecmd(cmd_str)
        else:
            # No -i and no command, what to do?
            # Print help or enter interactive mode? The user requested:
            # "I need the system to also work without interactive mode. Use -i for interactive and no command for normal terminal mode."
            # When the user just types "python main.py" without additional arguments, suggest methods.
            parser.print_help()
            
    except KeyboardInterrupt:
        print("\nServer interrupted by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()
