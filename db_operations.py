import mysql.connector
from mysql.connector import errorcode
from prettytable import PrettyTable
import matplotlib.pyplot as plt
import re
import json


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


def insert_default_data(conexao):
    ordem_execucao = [
        # Tabelas base (sem dependências)
        "taxon", "local_de_coleta", "funcionario", "categoria", 
        "laboratorio", "financiador", "projeto",
        
        # Tabelas com dependências simples
        "hierarquia", "especie", "equipamento",
        
        # Tabelas com dependências múltiplas
        "especime", "amostra", "artigo", "contrato", "financiamento",
        
        # Tabelas de relacionamento
        "proj_func", "proj_esp", "proj_cat", "registro_de_uso"
    ]
    
    for tabela in ordem_execucao:
        try:
            with open(f"data\\{tabela}.json", "r", encoding="utf-8") as file:
                json_str = file.read()
                json_dados = json.loads(json_str)  # Convertendo string para dict
            insert_data_from_json(conexao, tabela, json_dados)
        except FileNotFoundError:
            print(f"Arquivo JSON não encontrado.")
            continue
        except IOError as e:
            print(f"Erro ao ler arquivo JSON: {e}")
            continue


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


def validate_and_extract_records(json_dados, nome_tabela):
    """
    Valida e extrai registros do JSON.
    """
    if "registros" not in json_dados:
        raise ValueError("JSON deve conter a chave 'registros'")
    
    registros = json_dados["registros"]
    if not registros:
        print(f"Nenhum registro para inserir na tabela {nome_tabela}")
        return None

    return registros


def get_table_schema(conexao, nome_tabela):
    """
    Obtém o schema da tabela para verificar os tamanhos máximos das colunas.
    """
    cursor = conexao.cursor()
    cursor.execute(f"DESCRIBE `{nome_tabela}`")
    colunas_detalhes = cursor.fetchall()
    cursor.close()
    return {col[0]: col[1] for col in colunas_detalhes}


def build_insert_query(nome_tabela, campos):
    """
    Constrói a query de inserção.
    """
    placeholders = ", ".join(["%s"] * len(campos))
    campos_sql = ", ".join([f"`{c}`" for c in campos])
    return f"INSERT INTO `{nome_tabela}` ({campos_sql}) VALUES ({placeholders})"


def execute_insertions(conexao, registros, campos, schema_colunas, insert_query):
    """
    Executa as inserções na tabela.
    """
    cursor = conexao.cursor()
    sucessos, erros = 0, 0

    for registro in registros:
        try:
            valores = process_record(registro, campos, schema_colunas)
            cursor.execute(insert_query, tuple(valores))
            sucessos += 1
        except mysql.connector.Error as err:
            erros += 1
            handle_insertion_error(err, registro)

    conexao.commit()
    cursor.close()
    print(f"Tabela: {sucessos} inserções bem-sucedidas, {erros} erros")
    return sucessos > 0


def handle_insertion_error(err, registro):
    """
    Trata erros de inserção.
    """
    if err.errno == 1452:  # Foreign key constraint fails
        print(f"  → Erro FK: Chave estrangeira inválida em {registro}")
    elif err.errno == 1406:  # Data too long
        print(f"  → Erro: Dados muito longos em {registro}")
    else:
        print(f"  → Erro DB {err.errno}: {err} em {registro}")


def process_record(registro, campos, schema_colunas):
    """
    Processa e trunca os valores conforme necessário.
    """
    valores = []
    for campo in campos:
        valor = registro[campo]
        if campo in schema_colunas and "varchar" in schema_colunas[campo].lower():
            valor = truncate_varchar(valor, schema_colunas[campo])
        valores.append(valor)
    return valores


def truncate_varchar(valor, schema_info):
    """
    Trunca strings longas para campos varchar.
    """
    max_len_match = re.search(r'varchar\((\d+)\)', schema_info.lower())
    if max_len_match:
        max_len = int(max_len_match.group(1))
        if isinstance(valor, str) and len(valor) > max_len:
            print(f"  → Truncado valor de {len(valor)} para {max_len} caracteres")
            return valor[:max_len]
    return valor


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


def run_query(conexao, query, params=None):
    """
    Executa uma consulta SQL no banco de dados e exibe os resultados formatados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
        query (str): Consulta SQL a ser executada.
        params (tuple, opcional): Parâmetros para a consulta SQL, se necessário.
    Retorna:
        resultados (list): Lista de tuplas contendo os resultados da consulta.
    """
    cursor = conexao.cursor()
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
            
        resultados = cursor.fetchall()
        
        if resultados:
            tabela_formatada = PrettyTable()
            tabela_formatada.field_names = [col[0] for col in cursor.description]
            for linha in resultados:
                tabela_formatada.add_row(linha)
            print("\nResultados da Consulta:")
            print(tabela_formatada)
            
    except mysql.connector.Error as err:
        print(f"Erro ao executar a consulta: {err}")
        
    finally:
        cursor.close()
        return resultados


def plot_results(resultados):
    """
    Plota os resultados de uma consulta SQL usando matplotlib.
    Parâmetros:
        resultados (list): Lista de tuplas contendo os resultados da consulta.
    Retorna:
        None
    """
    try:
        categorias, qntdes = zip(*[(col[1], col[2]) for col in resultados])
    except ValueError:
        print("Resultados inválidos para plotagem.")
        return

    qntdes = [float(q) for q in qntdes]

    plt.barh(categorias, qntdes, color='skyblue')
    plt.ylabel('Categorias')
    plt.xlabel('Quantidade')
    plt.grid(axis='y', linestyle='--', alpha=0.7)

    for i, (cat, count) in enumerate(zip(categorias, qntdes)):
        plt.text(count - 0.5, i, str(count), va='center', ha='right', fontsize=10)

    plt.tight_layout()
    plt.show()


def query_by_user(conexao):
    """
    Permite ao usuário executar uma das consultas SQL disponíveis.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        None
    """
    print("\n" + "="*50)
    
    opcao = input("""\nConsultas disponíveis:

[ 1 ] > Quantidade de Funcionários com Contratos Ativos (por Projeto)
[ 2 ] > Quantidade de Usos de Equipamentos (por Laboratório)
[ 3 ] > Valor Médio de Financiamento (por Projeto)
[ 0 ] > Voltar ao Menu Principal

Opção: """).strip()

    if opcao == '1':
        data_ini = None
        data_fim = None
        query = """
        SELECT  p.ID_Proj, p.Nome, COUNT(*) AS Quantidade
        FROM    Projeto AS p, Proj_Func AS pf, Funcionario AS f, Contrato AS c
        WHERE   p.ID_Proj = pf.ID_Proj AND pf.ID_Func = f.ID_Func AND
                f.ID_Func = c.ID_Func AND c.Status = 'Ativo'
        GROUP BY 1,2
        ORDER BY 1;
            """   
    elif opcao == '2' or opcao == '3': 
        try:
            data_ini = input("\nDigite a data inicial (YYYY-MM-DD) da consulta: ").strip()
            data_fim = input("Digite a data final (YYYY-MM-DD) da consulta: ").strip()
        except ValueError:
            print("Data inválida. Por favor, digite no formato YYYY-MM-DD.")
            return
        if opcao == 2:
            query = """
            SELECT  l.ID_Lab, l.Nome, COUNT(*) AS Quantidade
            FROM    Laboratorio AS l, Equipamento AS e, Registro_de_Uso AS r
            WHERE   l.ID_Lab = e.ID_Lab AND e.ID_Equip = r.ID_Equip AND
                    r.Dt_Reg BETWEEN %s AND %s
            GROUP BY 1,2
            ORDER BY 1;
            """
        else:  # opcao == 3
            query = """
            SELECT  p.ID_Proj, p.Nome, ROUND(AVG(f.Valor), 2) AS Media
            FROM    Financiamento AS f, Projeto AS p, Artigo AS a
            WHERE   f.ID_Proj = p.ID_Proj AND p.ID_Proj = a.ID_Proj AND
                    a.Dt_Pub BETWEEN %s AND %s
            GROUP BY 1,2
            ORDER BY 1;
            """    
    elif opcao == 0:
        return
    else:
        print("Opção inválida. Por favor, escolha uma opção válida.")
        return
    
    try:
        if data_ini and data_fim:
            params = (data_ini, data_fim)
            resultados = run_query(conexao, query, params)
        else:
            resultados = run_query(conexao, query)
        if resultados:
            print("\nGráfico gerado na nova janela.")
            plot_results(resultados)
            return
    except mysql.connector.Error as err:
        print(f"Erro ao executar a consulta: {err}")


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


def make_query(conexao, sql_query):
    """Executa consulta SQL e exibe resultados formatados com melhor tratamento de erros."""
    cursor = conexao.cursor()
    
    try:
        print(f"\nExecutando consulta: {sql_query}")
        cursor.execute(sql_query)
        resultados = cursor.fetchall()
        
        if cursor.description:  # Para queries que retornam dados
            colunas = [desc[0] for desc in cursor.description]
            
            if resultados:
                print(f"\nResultados encontrados: {len(resultados)} registro(s)")
                tabela_formatada = PrettyTable()
                tabela_formatada.field_names = colunas
                
                # Exibe dados (limita a 20 registros para não sobrecarregar)
                for i, linha in enumerate(resultados[:20], 1):
                    tabela_formatada.add_row(linha)
                print(tabela_formatada)
                print("\n" + "="*50)
            else:
                print("Nenhum resultado encontrado para a consulta.")
                print("\nDicas:")
                print("   - Verifique se os dados existem nas tabelas")
                print("   - Tente usar termos mais genéricos na busca")
                print("   - Verifique a ortografia dos nomes")
        else:
            # Para queries que não retornam dados (INSERT, UPDATE, DELETE)
            print("Consulta executada com sucesso.")
            
    except mysql.connector.Error as err:
        print(f"Erro na execução da query: {err}")
        
        # Fornece dicas específicas baseado no tipo de erro
        codigo_erro = err.errno
        if codigo_erro == 1054:  # Unknown column
            print("\nPossíveis soluções:")
            print("   - Verifique se o nome da coluna está correto")
            print("   - Use aliases de tabela se houver ambiguidade (ex: t1.Nome)")
            print("   - Confirme se a coluna existe na tabela especificada")
        elif codigo_erro == 1146:  # Table doesn't exist
            print("\nPossíveis soluções:")
            print("   - Verifique se o nome da tabela está correto")
            print("   - Confirme se a tabela foi criada no banco de dados")
        elif codigo_erro == 1064:  # SQL syntax error
            print("\nPossíveis soluções:")
            print("   - Verifique a sintaxe SQL")
            print("   - Use aspas simples para strings")
            print("   - Confirme os JOINs e relacionamentos")
        else:
            print("\nTente reformular a consulta ou verifique a estrutura do banco.")
            
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
    finally:
        cursor.close()


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