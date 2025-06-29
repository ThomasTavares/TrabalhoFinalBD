import mysql.connector
from mysql.connector import errorcode
from prettytable import PrettyTable
import re
from ia_integration import validate_and_extract_records, get_table_schema, build_insert_query, execute_insertions


def connect_mysql(host="localhost", user="root", password="", database=None, port=3306):
    """
    Conecta-se a um banco de dados MySQL e retorna o objeto de conexão.

    Parâmetros:
        host (str): Host do servidor MySQL.
        user (str): Usuário para autenticação.
        password (str): Senha para autenticação.
        database (str, opcional): Nome do banco de dados a ser utilizado.
        port (int): Porta do servidor MySQL.

    Retorna:
        mysql.connector.connection.MySQLConnection ou None: Objeto de conexão se bem-sucedido, caso contrário None.
    """
    try:
        cnx = mysql.connector.connect(
            host=host, user=user, password=password, database=database, port=port, charset='utf8mb4', use_unicode=True
        )

        if cnx is not None and cnx.is_connected():
            print(f"Conectado ao MySQL em {host}:{port}")
            if database:
                print(f"Banco de dados selecionado: {database}")
            else:
                print("Nenhum banco de dados selecionado.")
            return cnx
    except mysql.connector.Error as err:
        print("Erro ao conectar ao MySQL:", err)
    return None


def create_tables(conexao):
    """
    Cria tabelas em um banco de dados MySQL a partir de um arquivo SQL.
    Esta função lê um arquivo SQL contendo comandos DDL (Data Definition Language),
    remove comentários e executa cada comando separadamente na conexão fornecida.
    Ela trata erros comuns, como tentativa de criar tabelas já existentes e erros de sintaxe,
    exibindo mensagens informativas para cada situação.
    Parâmetros:
        arquivo_sql (str): Caminho para o arquivo .sql contendo os comandos de criação das tabelas.
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        None
    """
    with open("script.sql", "r", encoding="utf-8") as f:
        script = f.read()

    # Remove comentários --, # e /* */ (Só para garantir)
    script = re.sub(r"/\*.*?\*/", "", script, flags=re.DOTALL)
    linhas = script.splitlines()
    script_limpo = "\n".join(
        l for l in linhas if not l.strip().startswith(("--", "#")) and l.strip()
    )

    # Divide as execuções até ;
    comandos = script_limpo.split(";")

    cursor = conexao.cursor()

    # Executa todos os comandos do script DDL
    for i, comando in enumerate(comandos):
        comando = comando.strip()
        if comando:
            try:
                cursor.execute(comando)
                print(f"[{i+1:02}] Executado: {comando.split()[0].upper()} ...")
            except mysql.connector.Error as err:
                erro_tipo = type(err).__name__
                erro_num = err.errno

                if erro_num == errorcode.ER_TABLE_EXISTS_ERROR:
                    tabela_match = re.search(
                        r"CREATE TABLE\s+`?(\w+)`?", comando, re.IGNORECASE
                    )
                    nome_tabela = tabela_match.group(1) if tabela_match else "desconhecida"
                    print(f"[{i+1:02}] Tabela '{nome_tabela}' já existe.")
                elif erro_num == errorcode.ER_PARSE_ERROR:
                    print(f"[{i+1:02}] Erro de sintaxe SQL:\n{comando}\n→ {err}")
                else:
                    print(
                        f"[{i+1:02}] {erro_tipo} ({erro_num}) ao executar:\n{comando}\n→ {err}"
                    )

    conexao.commit()
    cursor.close()
    return None


def insert_data(conexao, nome_tabela, campos, dados):
    """
    Wrapper para insert_data_from_json - converte dados de tupla para JSON.
    """
    # Converte lista de tuplas para formato JSON
    registros = []
    for linha in dados:
        registro = {campo: valor for campo, valor in zip(campos, linha)}
        registros.append(registro)
    
    json_dados = {"registros": registros}
    return insert_data_from_json(conexao, nome_tabela, json_dados)


def insert_data_from_json(conexao, nome_tabela, json_dados):
    """
    Insere dados em uma tabela a partir de um JSON estruturado.
    Retorna True se a inserção for bem-sucedida, False caso contrário.
    """
    registros = validate_and_extract_records(json_dados, nome_tabela)
    if not registros:
        return False

    schema_colunas = get_table_schema(conexao, nome_tabela)
    campos = list(registros[0].keys())
    insert_query = build_insert_query(nome_tabela, campos)

    return execute_insertions(conexao, registros, campos, schema_colunas, insert_query)


def drop_tables(conexao):
    """
    Remove todas as tabelas do banco de dados conectado.

    Esta função desativa temporariamente as restrições de chave estrangeira,
    busca todas as tabelas existentes no banco de dados e remove cada uma delas.
    Após a remoção, as restrições de chave estrangeira são reativadas.

    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.

    Retorna:
        None
    """
    
    try:
        cursor = conexao.cursor()

        # Desativar restrições de chave estrangeira
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")

        # Busca todas as tabelas
        cursor.execute("SHOW TABLES;")
        tabelas = cursor.fetchall()

        if not tabelas:
            print("Nenhuma tabela encontrada no banco.")
            return

        # Dropa as tabelas
        for (nome_tabela,) in tabelas:
            try:
                cursor.execute(f"DROP TABLE IF EXISTS `{nome_tabela}`;")
                print(f"Tabela '{nome_tabela.upper()}' removida.")
            except mysql.connector.Error as e:
                print(f"Erro ao deletar tabela '{nome_tabela.upper()}': {e}")

        # Reativa as restrições
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

        conexao.commit()
        cursor.close()

    except mysql.connector.Error as e:
        print("Erro ao deletar tabelas:", e)


def print_tables(conexao, print_flag=True):
    """
    Exibe as tabelas disponíveis no banco de dados conectado.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        dict: Um dicionário onde as chaves são os nomes das tabelas em minúsculo e os valores são os nomes reais das tabelas.
    """
    cursor = conexao.cursor()
    cursor.execute("SHOW TABLES;")
    resultado = cursor.fetchall()

    if not resultado:
        print("Nenhuma tabela encontrada.")
        return {}

    tabelas = {t[0].lower(): t[0] for t in resultado}

    if print_flag:
        for nome_real in tabelas.values():
            print(f"• {nome_real.upper()}")

    cursor.close()
    
    return tabelas


def show_table(conexao, tabela):
    """
    Exibe os valores registrados em uma tabela específica do banco de dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
        tabela (str): Nome da tabela a ser exibida.
    Retorna:
        int: Número de linhas exibidas na tabela, ou 0 se a tabela estiver vazia.
    """
    cursor = conexao.cursor()
    
    tabelas = print_tables(conexao, False)
    
    # Verificação case-insensitive usando o nome em minúsculo
    if tabela.lower() not in tabelas and tabela not in tabelas.values():
        print(f"Tabela '{tabela.upper()}' não encontrada.")
        cursor.close()
        return 0

    try:
        cursor.execute(f"SELECT * FROM `{tabela}`")
        linhas = cursor.fetchall()
        tabela_formatada = PrettyTable()
        tabela_formatada.field_names = [col[0] for col in cursor.description]
        if linhas:
            for linha in linhas:
                tabela_formatada.add_row(linha)
            print(tabela_formatada)
        else:
            print(f"A tabela '{tabela.upper()}' está vazia.")
    except mysql.connector.Error as err:
        print(f"Erro ao consultar: {err}")
    finally:
        cursor.close()
    
    # Retorna o número de linhas exibidas
    return len(linhas)


def show_tables(conexao):
    """
    Exibe as tabelas disponíveis no banco de dados conectado e permite ao usuário consultar o conteúdo de uma tabela específica.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        None
    """
    print("\n" + "="*50)
    print("\nTabelas Disponíveis:")

    # Mostra todas as tabelas
    tabelas = print_tables(conexao)

    # Entrada do usuário
    entrada = input("\nDigite o nome da tabela que deseja consultar: ").strip().lower()
    
    # Verificar se entrada existe antes de acessar
    if entrada not in tabelas:
        print(f"Tabela '{entrada.upper()}' não encontrada.")
        return
    
    nome_real = tabelas[entrada]
    print(f"\nTabela: {nome_real.upper()}")
    show_table(conexao, nome_real)
    
    print("\n" + "="*50)


def get_schema_info(conexao):
    """
    Obtém informações do schema de todas as tabelas do banco de dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados.
    Retorna:
        dict: Um dicionário onde as chaves são os nomes das tabelas e os valores são listas de dicionários
              contendo o nome e o tipo de cada coluna da tabela.
    """
    
    # Obtém o schema de todas as tabelas no banco de dados
    schema = {}
    cursor = conexao.cursor()
    cursor.execute("SHOW TABLES")
    tabelas = [linha[0] for linha in cursor.fetchall()]

    # Para cada tabela, obtém as colunas e seus tipos
    for tabela_nome in tabelas:
        cursor.execute(f"DESCRIBE `{tabela_nome}`")
        colunas = cursor.fetchall()
        schema[tabela_nome] = [{"nome": col[0], "tipo": col[1]} for col in colunas]

    cursor.close()
    return schema


def exit_db(conexao):
    """
    Encerra a conexão com o banco de dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Objeto de conexão com o banco de dados.
    Exceções:
        mysql.connector.Error: Caso ocorra um erro ao tentar encerrar a conexão.
    """
    
    try:
        if conexao.is_connected():
            conexao.close()
            print("Conexão com o banco de dados foi encerrada!")
        else:
            print("A conexão já estava encerrada.")
    except mysql.connector.Error as err:
        print(f"Erro ao encerrar a conexão: {err}")


