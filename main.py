import sys
import argparse
from cli import DataManagerCLI

def main():
    parser = argparse.ArgumentParser(description="DataManager Command Line Interface")
    parser.add_argument('-i', '--interactive', action='store_true', help="Iniciar no modo interativo")
    # Capturar argumentos extras que compõem o comando nativo sem disparar erro
    parser.add_argument('command', nargs=argparse.REMAINDER, help="Comando direto para execução")
    
    args = parser.parse_args()

    try:
        cli = DataManagerCLI()
        
        if args.interactive:
            # Roda o shell continuo
            cli.cmdloop()
        elif args.command:
            # Chegou comando como argumento sem a flag -i
            # Junta tudo como uma string e joga para o cmd nativo interpretar
            cmd_str = " ".join(args.command)
            # Desativa o banner intro
            cli.onecmd(cmd_str)
        else:
            # Sem -i e sem comando, o que fazer?
            # Imprime o help ou entra no modo interativo? O usuário pediu:
            # "preciso que o sistema tbm funcione sem o modo interativo. coloque o comando -i para interativo e sem comando para o modo de terminal normal."
            # Quando a pessoa apenas digita "python main.py" sem argumentos adicionais, sugerir os métodos.
            parser.print_help()
            
    except KeyboardInterrupt:
        print("\nServidor interrompido pelo usuário.")
        sys.exit(0)

if __name__ == "__main__":
    main()
