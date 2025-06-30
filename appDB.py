# pip install mysql-connector-python openai pillow transformers torch scikit-learn requests prettytable matplotlib duckduckgo_search
# Se possível usar VENV (virtualenv) para isolar as dependências do projeto
# Mude os dados da conexão com o MySQL (para usar o banco de dados local)

from db_operations import connect_mysql, create_tables, drop_tables, insert_default_data, show_tables, exit_db, get_schema_info, make_query, query_by_user
from manual_user import insert_by_user, update_by_user, delete_by_user
from ia_integration import  populate_all_tables, generate_sql_query
import mysql.connector


if __name__ == "__main__":
    try:
        # con = connect_mysql(host="localhost", user="usuario", password="Senha_1234", database="teste")
        con = connect_mysql(host="localhost", user="root", password="mysql", database="trabalho_final")

        if not con:
            print("Não foi possível conectar ao banco de dados.")
            exit(1)

        while True:
            print("""
╔═════════════════════════════════════════════╗
║             NEXUS-BIO CMD v1.4              ║
║---------------------------------------------║
║ [  1 ] > Criar Tabelas                      ║
║ [  2 ] > Apagar Tabelas                     ║
║ [  3 ] > Carregar Tabelas                   ║
║ [  4 ] > Visualizar Tabelas                 ║
║ [  5 ] > Consultar Tabelas                  ║
║ [  6 ] > Inserir Dados Manualmente          ║
║ [  7 ] > Atualizar Dados Manualmente        ║
║ [  8 ] > Deletar Dados Manualmente          ║
║ [  9 ] > IA: Preencher Tabelas              ║
║ [ 10 ] > IA: Gerar SQL a partir de Texto    ║
║ [  0 ] > Explodir Sistema                   ║
╚═════════════════════════════════════════════╝
""")

            try:
                opcao = int(input("Opção: ").strip())
                if opcao < 0 or opcao > 10:
                    print("Opção inválida. Escolha um número entre 0 e 10.")
                    continue
            except ValueError:
                print("Entrada inválida. Por favor, digite um número.")
                continue

            match opcao:
                case 0:
                    exit_db(con)
                    print("Saindo do NEXUS-BIO CMD...")
                    print("Preparando explosivos...")
                    break

                case 1:
                    create_tables(con)

                case 2:
                    drop_tables(con)
                    
                case 3:
                    insert_default_data(con)
                    
                case 4:
                    show_tables(con)
                    
                case 5:
                    query_by_user(con)
                    print("\n" + "="*50)

                case 6:
                    insert_by_user(con)

                case 7:
                    update_by_user(con)

                case 8:
                    delete_by_user(con)

                case 9:
                    n_linhas = input("Quantas linhas por tabela? [padrão=10]: ").strip()
                    n_linhas = int(n_linhas) if n_linhas.isdigit() and int(n_linhas) > 0 else 10
                    n_esp = n_linhas
                    populate_all_tables(con, n_linhas=n_linhas, n_especies=n_esp)

                case 10:
                    prompt_usuario = input("Digite sua consulta em linguagem natural: ").strip()
                    if prompt_usuario:
                        db_schema = get_schema_info(con)
                        query = generate_sql_query(prompt_usuario, db_schema, conexao=con)
                        if query:
                            print(f"Query gerada: {query}")
                            make_query(con, query)
                        else:
                            print("Erro: não foi possível gerar a query SQL")
                
                case _:
                    print("Opção inválida. Tente novamente.")

    except mysql.connector.Error as err:
        print("Erro na conexão com o banco de dados!", err)
    except KeyboardInterrupt:
        print("\n\nPrograma interrompido pelo usuário.")
    except FileNotFoundError as fnf_err:
        print(f"Erro de arquivo não encontrado: {fnf_err}")
    except ValueError as val_err:
        print(f"Erro de valor: {val_err}")
    except OSError as os_err:
        print(f"Erro do sistema operacional: {os_err}")
    except (RuntimeError, AttributeError, TypeError) as e:
        print(f"Erro inesperado: {e}")
    finally:
        if 'con' in locals() and con.is_connected():
            exit_db(con)
# Fim do script principal