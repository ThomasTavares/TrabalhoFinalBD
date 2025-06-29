# pip install mysql-connector-python openai pillow transformers torch scikit-learn requests prettytable
# Se possível usar VENV (virtualenv) para isolar as dependências do projeto
# Mude os dados da conexão com o MySQL (para usar o banco de dados local)

from db_operations import connect_mysql, create_tables, drop_tables, show_tables, exit_db, get_schema_info
from manual_user import insert_by_user, update_by_user, delete_by_user
from ia_integration import  populate_all_tables, generate_sql_query, make_query, search_similarity
import mysql.connector

def crud(conexao):
    # Exemplo de CRUD completo usando as funções já implementadas
    
    # 1. Deletar todas as tabelas (limpa o banco)
    print("\n[CRUD] Deletando todas as tabelas...")
    drop_tables(conexao)

    # 2. Criar todas as tabelas a partir do arquivo script.sql
    print("\n[CRUD] Criando tabelas a partir de 'script.sql'...")
    create_tables(conexao)

    # 3. Popular todas as tabelas automaticamente com dados gerados por IA
    print("\n[CRUD] Populando tabelas automaticamente...")
    populate_all_tables(conexao, n_linhas=10)

    # 4. Mostrar dados de todas as tabelas
    print("\n[CRUD] Exibindo dados de todas as tabelas:")
    schema = get_schema_info(conexao)
    for tabela_nome in schema:
        print(f"\n--- {tabela_nome.upper()} ---")
        cursor = conexao.cursor()
        cursor.execute(f"SELECT * FROM `{tabela_nome}`")
        linhas = cursor.fetchall()
        for linha in linhas:
            print(linha)
        cursor.close()

    print("\n[CRUD] CRUD automatizado finalizado.")


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
║ [  3 ] > Visualizar Tabelas                 ║
║ [  4 ] > Inserir Dados Manualmente          ║
║ [  5 ] > Atualizar Dados Manualmente        ║
║ [  6 ] > Deletar Dados Manualmente          ║
║ [  7 ] > IA: Preencher Tabelas              ║
║ [  8 ] > IA: Gerar SQL a partir de Texto    ║
║ [  9 ] > IA: Buscar Imagens Similares       ║
║ [ 10 ] > Executar CRUD Automático           ║
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
                    show_tables(con)

                case 4:
                    insert_by_user(con)

                case 5:
                    update_by_user(con)

                case 6:
                    delete_by_user(con)

                case 7:
                    n_linhas = input("Quantas linhas por tabela? [padrão=10]: ").strip()
                    n_linhas = int(n_linhas) if n_linhas.isdigit() and int(n_linhas) > 0 else 10
                    n_esp = input("Quantas espécies? [padrão=5]: ").strip()
                    n_esp = int(n_esp) if n_esp.isdigit() and int(n_esp) > 0 else 100
                    populate_all_tables(con, n_linhas=n_linhas, n_especies=n_esp)

                case 8:
                    prompt_usuario = input("Digite sua consulta em linguagem natural: ").strip()
                    if prompt_usuario:
                        db_schema = get_schema_info(con)
                        query = generate_sql_query(prompt_usuario, db_schema)
                        if query:
                            print(f"Query gerada: {query}")
                            make_query(con, query)
                        else:
                            print("Erro: não foi possível gerar a query SQL")
                
                case 9:
                    caminho_imagem = input("Caminho da imagem para busca: ").strip()
                    try:
                        with open(caminho_imagem, "rb") as f:
                            imagem_bytes = f.read()
                        search_similarity(con, imagem_consulta_bytes=imagem_bytes)
                    except FileNotFoundError:
                        print(f"Arquivo '{caminho_imagem}' não encontrado.")
                    except OSError as e:
                        print(f"Erro ao processar a imagem: {e}")
                
                case 10:
                    print("\nIniciando CRUD Automático...")
                    crud(con)

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