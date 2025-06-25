# pip install mysql-connector-python openai pillow transformers torch scikit-learn
# Se possível usar VENV (virtualenv) para isolar as dependências do projeto
# Mude os dados da conexão com o MySQL (para usar o banco de dados local)

import re
import ast
import io
from collections import defaultdict, deque

import openai
import mysql.connector
from mysql.connector import errorcode

from PIL import Image
import numpy as np

from sklearn.metrics.pairwise import cosine_similarity
from transformers import CLIPProcessor, CLIPModel
import torch

# Carrega o modelo e o processador CLIP
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch16")
clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch16")

openai.api_key = "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"


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
            host=host, user=user, password=password, database=database, port=port
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


def create_tables(arquivo_sql, conexao):
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
    with open(arquivo_sql, "r", encoding="utf-8") as f:
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
                print(f"Tabela '{nome_tabela}' removida.")
            except mysql.connector.Error as e:
                print(f"Erro ao deletar tabela '{nome_tabela}': {e}")

        # Reativa as restrições
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

        conexao.commit()
        cursor.close()

    except mysql.connector.Error as e:
        print("Erro ao deletar tabelas:", e)


def show_table(conexao):
    """
    Exibe as tabelas disponíveis no banco de dados conectado e permite ao usuário consultar o conteúdo de uma tabela específica.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        None
    """
    
    print("\n--- TABELAS DISPONÍVEIS ---")
    cursor = conexao.cursor()

    # Mostra todas as tabelas
    cursor.execute("SHOW TABLES;")
    resultado = cursor.fetchall()

    if not resultado:
        print("Nenhuma tabela encontrada.")
        return

    tabelas = {t[0].lower(): t[0] for t in resultado}

    for nome_real in tabelas.values():
        print(f"• {nome_real}")

    # Entrada do usuário
    entrada = input("\nDigite o nome da tabela que deseja consultar: ").strip().lower()

    if entrada not in tabelas:
        print(f"Tabela '{entrada}' não encontrada (case-insensitive).")
        return

    nome_real = tabelas[entrada]

    try:
        cursor.execute(f"SELECT * FROM `{nome_real}`")
        linhas = cursor.fetchall()
        if linhas:
            print(f"\nTABELA: {nome_real}")
            for linha in linhas:
                print(linha)
        else:
            print(f"A tabela '{nome_real}' está vazia.")
    except mysql.connector.Error as err:
        print(f"Erro ao consultar: {err}")
    finally:
        cursor.close()


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


def get_foreign_key_dependencies(conexao):
    """
    Obtém o grafo de dependências de chaves estrangeiras entre tabelas do banco de dados conectado.
    Esta função consulta o banco de dados para identificar todas as relações de chave estrangeira
    entre as tabelas do schema atual, construindo um grafo direcionado onde cada nó representa
    uma tabela e as arestas indicam dependências de chave estrangeira. Também retorna um dicionário
    detalhando as relações de cada tabela.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        tuple:
            - grafo (defaultdict): Grafo de dependências, onde as chaves são nomes de tabelas e os valores
              são conjuntos de tabelas das quais dependem via chave estrangeira.
            - relacoes (defaultdict): Dicionário onde as chaves são nomes de tabelas e os valores são listas
              de dicionários detalhando as colunas de chave estrangeira e suas referências.
    """
    
    # Obtém as dependências de chaves estrangeiras entre tabelas
    cursor = conexao.cursor()
    query = """
        SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND REFERENCED_TABLE_NAME IS NOT NULL
    """
    cursor.execute(query)
    deps = cursor.fetchall()
    cursor.close()

    # Cria o grafo de dependências e as relações
    grafo = defaultdict(set)
    todas_tabelas = set()
    relacoes = defaultdict(list)

    # Preenche o grafo e as relações
    # Cada entrada é (tabela, coluna, ref_tabela, ref_coluna)
    for tabela_fk, coluna, ref_tabela, ref_coluna in deps:
        grafo[tabela_fk].add(ref_tabela)
        todas_tabelas.update([tabela_fk, ref_tabela])
        relacoes[tabela_fk].append({
            'coluna': coluna,
            'ref_tabela': ref_tabela,
            'ref_coluna': ref_coluna
        })

    # Garante que todas as tabelas estão no grafo, mesmo sem dependências
    for tabela_nome in todas_tabelas:
        grafo.setdefault(tabela_nome, set())

    return grafo, relacoes


def topological_sort(grafo):
    """
    Realiza a ordenação topológica de um grafo direcionado.
    Parâmetros:
        grafo (dict): Um dicionário representando o grafo, onde as chaves são os nós e os valores são listas de nós adjacentes.
    Retorna:
        list: Uma lista de nós ordenados topologicamente. Caso o grafo contenha ciclos, os nós restantes (não visitados) são adicionados ao final da lista.
    """
    
    # Realiza a ordenação topológica de um grafo
    in_degree = {u: 0 for u in grafo}
    for u in grafo:
        for v in grafo[u]:
            in_degree[v] += 1

    # Inicializa a fila com todos os nós de grau de entrada 0
    fila = deque([u for u in grafo if in_degree[u] == 0])
    ordenado = []
    visitados = set()

    while fila:
        u = fila.popleft()
        visitados.add(u)
        ordenado.append(u)
        for v in grafo[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0 and v not in visitados:
                fila.append(v)

    # Verifica se todos os nós foram visitados
    restantes = [u for u in grafo if u not in visitados]
    return ordenado + restantes


def build_prompt(schema: dict, tabela_alvo: str, n_linhas=20):
    """
    Gera um prompt para criação de dados fictícios para uma tabela específica de um schema.
    Parâmetros:
        schema (dict): Dicionário contendo o schema do banco de dados, onde as chaves são os nomes das tabelas e os valores são listas de dicionários com informações das colunas.
        tabela_alvo (str): Nome da tabela para a qual os dados devem ser gerados.
        n_linhas (int, opcional): Número de linhas de dados a serem geradas. Padrão é 20.
    Retorna:
        str: Prompt formatado solicitando a geração dos dados no formato de lista de tuplas Python.
    """
    campos_str = "\n".join(
        f"- `{col['nome']}`: {col['tipo']}" for col in schema[tabela_alvo]
    )

    
    prompt = f"""
    Gere exatamente {n_linhas} linhas de dados realistas e coerentes para a tabela `{tabela_alvo}`, com base no seguinte esquema de banco de dados:
    
    {campos_str}
    
    Sua resposta deve ser APENAS uma lista Python de tuplas, cada tupla representando uma linha de inserção. NÃO inclua explicações, comentários, descrições, texto extra, cabeçalhos ou rodapés.
    
    Formato EXATO da resposta:
    [
        (valor1, valor2, ...),
        (valor1, valor2, ...),
        ...
    ]
    
    A resposta deve ser apenas a lista acima, nada mais. Se retornar qualquer coisa além da lista, será considerado erro.
    """
    return prompt.strip()


def generate_data(prompt, modelo="gpt-4o-mini", temperatura=0.4):
    """     
        Gera dados a partir de um prompt utilizando um modelo da OpenAI.
        Parâmetros:
            prompt (str): Texto de entrada que será enviado ao modelo para geração de dados.
            modelo (str, opcional): Nome do modelo OpenAI a ser utilizado. Padrão é "gpt-4o-mini".
            temperatura (float, opcional): Grau de aleatoriedade na geração do texto. Padrão é 0.4.
        Retorna:
            str: Texto gerado pelo modelo OpenAI em resposta ao prompt fornecido.
    """

    # Gera dados usando o modelo OpenAI
    response = openai.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperatura,
    )
    return response.choices[0].message.content


def insert_data(conexao, nome_tabela, campos, dados):
    """
    Insere múltiplas linhas de dados em uma tabela específica do banco de dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados.
        nome_tabela (str): Nome da tabela onde os dados serão inseridos.
        campos (list): Lista com os nomes das colunas da tabela.
        dados (list of tuple): Lista de tuplas, onde cada tupla representa uma linha de valores a ser inserida.
    """
    
    # Insere dados na tabela especificada
    cursor = conexao.cursor()
    placeholders = ", ".join(["%s"] * len(campos))
    campos_sql = ", ".join([f"`{c}`" for c in campos])
    query = f"INSERT INTO `{nome_tabela}` ({campos_sql}) VALUES ({placeholders})"
    for linha in dados:
        try:
            cursor.execute(query, linha)
        except mysql.connector.Error as err:
            print(f"Erro ao inserir na tabela `{nome_tabela}`: {err}")

    conexao.commit()
    cursor.close()


def populate_all_tables_ordered(conexao, n_linhas=10):
    """
    Popula todas as tabelas do banco de dados na ordem correta considerando dependências de chaves estrangeiras.
    Primeiro, obtém o schema das tabelas e as dependências de chaves estrangeiras. Em seguida, realiza uma ordenação topológica para determinar a ordem de inserção dos dados, garantindo que tabelas dependentes sejam populadas após suas referências. Para cada tabela, verifica se já possui registros e, caso contrário, gera dados fictícios (sem as colunas de chave estrangeira) e insere na tabela. Ignora tabelas já populadas e trata erros de formatação dos dados gerados.
    Parâmetros:
        conexao: objeto de conexão com o banco de dados.
        n_linhas (int): número de linhas a serem inseridas em cada tabela (padrão: 10).
    """
    
    # Pega o schema e as dependências de chaves estrangeiras
    schema = get_schema_info(conexao)
    grafo, relacoes = get_foreign_key_dependencies(conexao)
    ordem = topological_sort(grafo)

    # Popula as tabelas na ordem topológica sem as FKs
    for tabela_nome in ordem:
        print(f"\nTabela: `{tabela_nome}`")
        try:
            cursor = conexao.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_nome}`")
            total = cursor.fetchone()[0]
            cursor.close()
            if total > 0:
                print(f"Tabela `{tabela_nome}` já contém {total} registros. Ignorando.")
                continue

            campos = [col["nome"] for col in schema[tabela_nome]]
            fks = {rel['coluna'] for rel in relacoes.get(tabela_nome, [])}
            campos_sem_fk = [c for c in campos if c not in fks]

            prompt = build_prompt(
                {t: schema[t] for t in [tabela_nome]},
                tabela_nome,
                n_linhas=n_linhas
            )
            resposta = generate_data(prompt)

            try:
                dados = ast.literal_eval(resposta)
                if not isinstance(dados, list) or not all(isinstance(x, tuple) for x in dados):
                    raise ValueError("Formato inválido: esperado lista de tuplas")
            except ValueError as e:
                print(f"Dados inválidos retornados pela IA para `{tabela_nome}` → {e}")
                continue

            dados_sem_fk = [tuple(v for i, v in enumerate(linha) if campos[i] in campos_sem_fk) for linha in dados]

            insert_data(conexao, tabela_nome, campos_sem_fk, dados_sem_fk)
            print(f"Populada `{tabela_nome}` parcialmente (sem FKs).")
        except ValueError as e:
            print(f"Erro ao processar `{tabela_nome}`: {e}")


def update_foreign_keys(conexao):
    """
    Atualiza os valores das chaves estrangeiras em tabelas de um banco de dados após inserções parciais.
    Esta função percorre todas as tabelas e suas relações de chave estrangeira, obtidas pela função 
    `get_foreign_key_dependencies`, e preenche os campos de chave estrangeira que estão nulos com valores 
    válidos da tabela referenciada. O processo é feito apenas para registros que ainda não possuem valor 
    definido na coluna de chave estrangeira.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados.
    Efeitos colaterais:
        - Atualiza registros nas tabelas do banco de dados, preenchendo chaves estrangeiras nulas.
        - Realiza commit das alterações ao final do processo.
        - Exibe mensagem no console ao término da atualização.
    Observações:
        - Assume que a função `get_foreign_key_dependencies` retorna corretamente as relações de chaves estrangeiras.
        - O preenchimento é feito apenas para o número de registros existentes nas tabelas referenciadas.
        - Utiliza SQL dinâmico; recomenda-se cuidado para evitar SQL Injection.
    """
    
    # Atualiza as chaves estrangeiras após inserção parcial
    _, relacoes = get_foreign_key_dependencies(conexao)

    cursor = conexao.cursor()
    
    # Para cada tabela, atualiza as chaves estrangeiras
    for tabela_nome in relacoes:
        for rel in relacoes[tabela_nome]:
            col = rel['coluna']
            ref_tabela = rel['ref_tabela']
            ref_coluna = rel['ref_coluna']

            cursor.execute(f"SELECT `{ref_coluna}` FROM `{ref_tabela}`")
            valores = [linha[0] for linha in cursor.fetchall()]
            if not valores:
                continue

            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_nome}`")
            total = cursor.fetchone()[0]
            if total == 0:
                continue

            cursor.execute(f"SELECT `id` FROM (SELECT `{col}`, ROW_NUMBER() OVER () as id FROM `{tabela_nome}`) as temp")
            ids = [i + 1 for i in range(len(valores))]

            for i, val in enumerate(valores[:len(ids)]):
                cursor.execute(f"UPDATE `{tabela_nome}` SET `{col}` = %s WHERE `{col}` IS NULL LIMIT 1", (val,))

    conexao.commit()
    cursor.close()
    print("Chaves estrangeiras atualizadas após inserção parcial.")


def update_random_rows(conexao, tabela_nome, n_linhas=5, modelo="gpt-4o-mini", temperatura=0.4):
    """
    Atualiza aleatoriamente um número especificado de linhas em uma tabela de banco de dados com novos valores realistas, utilizando um modelo de IA para gerar os dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
        tabela_nome (str): Nome da tabela cujas linhas serão atualizadas.
        n_linhas (int, opcional): Número de linhas aleatórias a serem atualizadas. Padrão é 5.
        modelo (str, opcional): Nome do modelo de IA a ser utilizado para gerar os novos dados. Padrão é "gpt-4o-mini".
        temperatura (float, opcional): Temperatura do modelo de IA, controlando a aleatoriedade das respostas. Padrão é 0.4.
    """
    
    schema = get_schema_info(conexao)
    if tabela_nome not in schema:
        print(f"Tabela `{tabela_nome}` não encontrada.")
        return

    cursor = conexao.cursor(dictionary=True)
    cursor.execute(f"SELECT * FROM `{tabela_nome}` ORDER BY RAND() LIMIT {n_linhas}")
    linhas = cursor.fetchall()
    cursor.close()

    if not linhas:
        print(f"Tabela `{tabela_nome}` está vazia. Nada para atualizar.")
        return

    campos_str = "\n".join(
        f"- `{col['nome']}`: {col['tipo']}" for col in schema[tabela_nome]
    )

    for idx, linha in enumerate(linhas, start=1):
        prompt = f"""
            Atualize os dados da seguinte linha na tabela `{tabela_nome}` com novos valores realistas e diferentes, mantendo a estrutura do schema:

            {campos_str}

            Linha original:
            {linha}

            Gere a nova linha como um dicionário Python, com os mesmos campos e valores atualizados. A chave primária deve manter o mesmo valor.
        """
        resposta = generate_data(prompt, modelo=modelo, temperatura=temperatura)
        try:
            nova_linha = ast.literal_eval(resposta)
            update_query = ", ".join(
                [f"`{k}` = %s" for k in nova_linha if k != list(linha.keys())[0]]
            )
            where = f"`{list(linha.keys())[0]}` = %s"
            valores = [nova_linha[k] for k in nova_linha if k != list(linha.keys())[0]]
            valores.append(linha[list(linha.keys())[0]])

            cursor = conexao.cursor()
            cursor.execute(
                f"UPDATE `{tabela_nome}` SET {update_query} WHERE {where}", valores
            )
            conexao.commit()
            cursor.close()
            print(f"Linha {idx}/{n_linhas} de `{tabela_nome}` atualizada com sucesso.")
        except (ValueError, SyntaxError) as e:
            print(
                f"Erro ao interpretar resposta da IA na linha {idx} → {e}"
            )
        except mysql.connector.Error as e:
            print(
                f"Erro ao executar o update na linha {idx} → {e}"
            )


def delete_random_rows(conexao, tabela_nome, n_linhas=5):
    """
    Remove aleatoriamente um número especificado de linhas de uma tabela em um banco de dados MySQL.
    Esta função identifica a chave primária da tabela fornecida, seleciona aleatoriamente `n_linhas` registros
    e os deleta da tabela. Caso a tabela não possua chave primária ou esteja vazia, a função exibe uma mensagem
    apropriada e não realiza nenhuma exclusão.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados.
        tabela_nome (str): Nome da tabela de onde as linhas serão removidas.
        n_linhas (int, opcional): Número de linhas a serem deletadas aleatoriamente. Padrão é 5.
    Retorna:
        None  
    """
    cursor = conexao.cursor()

    # Descobre a chave primária
    cursor.execute(
        """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_KEY = 'PRI'
        """,
        (tabela_nome,),
    )
    pk = cursor.fetchone()
    if not pk:
        print(f"Não foi possível identificar a chave primária da tabela `{tabela_nome}`.")
        cursor.close()
        return
    pk_col = pk[0]

    # Busca valores aleatórios
    cursor.execute(
        f"SELECT `{pk_col}` FROM `{tabela_nome}` ORDER BY RAND() LIMIT {n_linhas}"
    )
    pk_vals = cursor.fetchall()
    if not pk_vals:
        print(f"Tabela `{tabela_nome}` está vazia.")
        cursor.close()
        return

    deletados = 0
    for (pk_val,) in pk_vals:
        cursor.execute(f"DELETE FROM `{tabela_nome}` WHERE `{pk_col}` = %s", (pk_val,))
        deletados += 1

    conexao.commit()
    cursor.close()
    print(f"{deletados} linha(s) deletada(s) de `{tabela_nome}`.")


def update_by_user(conexao):
    """
    Solicita ao usuário o nome da tabela, o campo a ser atualizado, o novo valor e uma condição WHERE,
    depois executa uma operação UPDATE na tabela especificada usando os parâmetros fornecidos.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    """
    tabela_nome = input("Tabela: ").strip()
    campo = input("Campo a atualizar: ").strip()
    valor = input("Novo valor: ").strip()
    condicao = input("Condição WHERE (ex: id = 3): ").strip()

    query = f"UPDATE `{tabela_nome}` SET `{campo}` = %s WHERE {condicao}"
    try:
        cursor = conexao.cursor()
        cursor.execute(query, (valor,))
        conexao.commit()
        cursor.close()
        print("Atualização feita com sucesso.")
    except mysql.connector.Error as err:
        print(f"Erro: {err}")


def delete_by_user(conexao):
    """
    Deleta linhas de uma tabela do banco de dados com base em uma condição fornecida pelo usuário.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    """
    
    tabela_nome = input("Tabela: ").strip()
    condicao = input("Condição WHERE (ex: id = 1): ").strip()

    query = f"DELETE FROM `{tabela_nome}` WHERE {condicao}"
    try:
        cursor = conexao.cursor()
        cursor.execute(query)
        conexao.commit()
        cursor.close()
        print("Linhas deletadas com sucesso.")
    except mysql.connector.Error as err:
        print(f"Erro: {err}")


def generate_sql_query(user_prompt, schema, modelo="gpt-4o-mini", temperatura=0.3):
    """
    Gera uma query SQL baseada em um pedido do usuário e em um schema de banco de dados fornecido.
    Esta função identifica tabelas relevantes mencionadas no texto do usuário, monta um schema reduzido
    contendo apenas essas tabelas (ou todas, caso nenhuma seja identificada), e constrói um prompt para
    um modelo de linguagem gerar a query SQL correspondente ao pedido.
    Parâmetros:
        user_prompt (str): Pedido do usuário em linguagem natural descrevendo a consulta desejada.
        schema (dict): Dicionário representando o schema do banco de dados, onde as chaves são nomes de tabelas
            e os valores são listas de dicionários com informações das colunas (devem conter a chave 'nome').
        modelo (str, opcional): Nome do modelo de linguagem a ser utilizado para gerar a query. Padrão: "gpt-4o-mini".
        temperatura (float, opcional): Parâmetro de temperatura para o modelo de linguagem, controlando a aleatoriedade
            da resposta. Padrão: 0.3.
    Retorno:
        str: Query SQL gerada pelo modelo de linguagem, sem explicações adicionais.
    """
    
    # Tenta identificar tabelas mencionadas no texto do usuário
    texto = user_prompt.lower()
    tabelas_relevantes = []
    for tabela_nome in schema:
        if tabela_nome.lower() in texto:
            tabelas_relevantes.append(tabela_nome)
            
    # Se não encontrar nenhuma, usa todas (fallback)
    if not tabelas_relevantes:
        tabelas_relevantes = list(schema.keys())
    schema_reduzido = {t: schema[t] for t in tabelas_relevantes if t in schema}

    # Monta o schema enxuto para o prompt
    campos_str = "\n".join(
        f"- {t}: {', '.join([col['nome'] for col in schema_reduzido[t]])}"
        for t in schema_reduzido
    )

    prompt = f"""
        Você é um assistente SQL. Gere APENAS a query SQL correspondente ao pedido abaixo, usando o seguinte schema (tabelas e colunas):
        
        {campos_str}
        
        Pedido do usuário:
        \"\"\"{user_prompt}\"\"\"
        
        IMPORTANTE:
        - NÃO inclua explicações, comentários, texto extra, cabeçalhos ou rodapés.
        - NÃO adicione nada além da query SQL.
        - Retorne SOMENTE a query SQL, em uma única linha, pronta para ser executada.
        
        Exemplo de resposta correta:
        SELECT * FROM tabela WHERE condicao;
        
        Se retornar qualquer coisa além da query SQL, será considerado erro.
    """
    resposta = generate_data(prompt, modelo=modelo, temperatura=temperatura)
    return resposta.strip()


def make_query(conexao, sql_query):
    """
    Executa uma consulta SQL na conexão fornecida e exibe os resultados.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados.
        sql_query (str): Consulta SQL a ser executada.
    """
    
    try:
        cursor = conexao.cursor()
        cursor.execute(sql_query)
        resultados = cursor.fetchall()
        colunas = [desc[0] for desc in cursor.description]
        cursor.close()

        if resultados:
            print(f"Resultados da query '{sql_query}':")
            for linha in resultados:
                print(dict(zip(colunas, linha)))
        else:
            print("Nenhum resultado encontrado.")
    except mysql.connector.Error as err:
        print(f"Erro ao executar a query: {err}")
        
    cursor.close()


def generate_embeddings(img_bytes):
    """
    Gera um vetor de embedding normalizado para uma imagem fornecida em bytes.
    Parâmetros:
        img_bytes (bytes): Os bytes da imagem a ser processada.
    Retorna:
        np.ndarray ou None: O vetor de embedding normalizado da imagem, ou None em caso de erro.
    """
    
    try:
        imagem = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        print(f"Erro ao abrir imagem: {e}")
        return None

    try:
        inputs = clip_processor(images=imagem, return_tensors="pt")
        with torch.no_grad():
            embedding = clip_model.get_image_features(**inputs)
        embedding_np = embedding[0].cpu().numpy()
        # Normaliza o vetor para facilitar comparação de similaridade
        norm = np.linalg.norm(embedding_np)
        if norm == 0:
            return embedding_np
        return embedding_np / norm
    except Exception as e:
        print(f"Erro ao gerar embedding: {e}")
        return None


def search_similarity(conexao, imagem_consulta_bytes, top_k=3):
    """
    Busca as imagens mais similares à imagem de consulta no banco de dados, utilizando embeddings e similaridade de cosseno.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados.
        imagem_consulta_bytes (bytes): Imagem de consulta em formato de bytes.
        top_k (int, opcional): Número de imagens mais similares a serem retornadas. Padrão é 3.
    Retorna:
        None. Exibe no console as imagens mais similares, suas similaridades e informações da espécie associada.
    """
    
    cursor = conexao.cursor()
    cursor.execute("SELECT ID_Midia, Dado FROM Midia")
    midias = cursor.fetchall()
    cursor.close()

    if not midias:
        print("Nenhuma imagem cadastrada.")
        return

    # Gere embedding da imagem de consulta
    emb_consulta = generate_embeddings(imagem_consulta_bytes)

    # Gere embeddings das imagens do banco
    embeddings = []
    ids = []
    for id_midia, dado in midias:
        try:
            emb = generate_embeddings(dado)
            embeddings.append(emb)
            ids.append(id_midia)
        except Exception as e:
            print(f"Erro ao processar imagem ID {id_midia}: {e}")

    if not embeddings:
        print("Nenhuma imagem válida para comparar.")
        return

    # Calcule similaridade
    sims = cosine_similarity([emb_consulta], embeddings)[0]
    top_idx = np.argsort(sims)[::-1][:top_k]

    print("Imagens mais similares e suas espécies:")
    cursor = conexao.cursor()
    for i in top_idx:
        id_midia = ids[i]
        # Busca nome e descrição da espécie associada à mídia
        cursor.execute("""
            SELECT e.Nome, e.Descricao
            FROM Midia m
            JOIN Esp_Midia em ON m.ID_Midia = em.ID_Midia
            JOIN Especime es ON em.ID_Especime = es.ID_Especime
            JOIN Especie e ON es.ID_Esp = e.ID_Esp
            WHERE m.ID_Midia = %s
            LIMIT 1
        """, (id_midia,))
        especie = cursor.fetchone()
        if especie:
            nome, descricao = especie
        else:
            nome, descricao = "Espécie não encontrada", "-"
        print(f"ID_Midia: {id_midia}, Similaridade: {sims[i]:.3f}, Espécie: {nome}, Descrição: {descricao}")
    cursor.close()


def exit_db(connect):
    """
    Encerra a conexão com o banco de dados.
    Parâmetros:
        connect (mysql.connector.connection.MySQLConnection): Objeto de conexão com o banco de dados.
    Exceções:
        mysql.connector.Error: Caso ocorra um erro ao tentar encerrar a conexão.
    """
    
    try:
        if connect.is_connected():
            connect.close()
            print("Conexão com o banco de dados foi encerrada!")
        else:
            print("A conexão já estava encerrada.")
    except mysql.connector.Error as err:
        print(f"Erro ao encerrar a conexão: {err}")


def crud(connect):
    # Exemplo de CRUD completo usando as funções já implementadas

    # 1. Deletar todas as tabelas (limpa o banco)
    print("\n[CRUD] Deletando todas as tabelas...")
    drop_tables(connect)

    # 2. Criar todas as tabelas a partir do arquivo schema.sql
    print("\n[CRUD] Criando tabelas a partir de 'schema.sql'...")
    create_tables("schema.sql", connect)

    # 3. Popular todas as tabelas automaticamente com dados gerados por IA
    print("\n[CRUD] Populando tabelas automaticamente...")
    populate_all_tables_ordered(connect, n_linhas=10)
    update_foreign_keys(connect)

    # 4. Mostrar dados de todas as tabelas
    print("\n[CRUD] Exibindo dados de todas as tabelas:")
    schema = get_schema_info(connect)
    for tabela in schema:
        print(f"\n--- {tabela} ---")
        cursor = connect.cursor()
        cursor.execute(f"SELECT * FROM `{tabela}`")
        linhas = cursor.fetchall()
        for linha in linhas:
            print(linha)
        cursor.close()

    # 5. Atualizar algumas linhas aleatórias de uma tabela (exemplo: primeira tabela)
    tabela_exemplo = next(iter(schema))
    print(f"\n[CRUD] Atualizando 3 linhas aleatórias da tabela '{tabela_exemplo}'...")
    update_random_rows(connect, tabela_nome=tabela_exemplo, n_linhas=3)

    # 6. Deletar algumas linhas aleatórias da mesma tabela
    print(f"\n[CRUD] Deletando 2 linhas aleatórias da tabela '{tabela_exemplo}'...")
    delete_random_rows(connect, tabela_nome=tabela_exemplo, n_linhas=2)

    # 7. Atualização manual (exemplo)
    print(f"\n[CRUD] Atualização manual na tabela '{tabela_exemplo}' (exemplo)...")
    # update_by_user(connect)  # Descomente para interação manual

    # 8. Deleção manual (exemplo)
    print(f"\n[CRUD] Deleção manual na tabela '{tabela_exemplo}' (exemplo)...")
    # delete_by_user(connect)  # Descomente para interação manual

    print("\n[CRUD] CRUD automatizado finalizado.")


if __name__ == "__main__":
    try:
        # Altere pro nosso banco de dados (usuario, senha, database)
        con = connect_mysql(host="localhost", user="root", password="mysql", database="trabalho_final")

        if not con:
            print("Não foi possível conectar ao banco de dados.")
            exit(1)

        while True:
            print(
                """
                ░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░
                ░▒   NEXUS-BIO CMD v1.3.2  ▒░
                ░▒------------------------ ▒░
                ░▒ [0x01] > Criar Tabelas  ▒░
                ░▒ [0x02] > Apagar Tabelas ▒░
                ░▒ [0x03] > IA: Preencher  ▒░
                ░▒ [0x04] > Visualizar     ▒░
                ░▒ [0x05] > IA: Atualizar  ▒░
                ░▒ [0x06] > Remover Dados  ▒░
                ░▒ [0x07] > Update Manual  ▒░
                ░▒ [0x08] > Deletar Manual ▒░
                ░▒ [0x09] > IA: SQL Texto  ▒░
                ░▒ [0x0A] > IA: Imagens    ▒░
                ░▒ [0xFF] > CRUD           ▒░
                ░▒ [0x00] > Explodir UFSC  ▒░
                ░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░
                """
            )


            try:
                opcao = int(input("Opção: "))
            except ValueError:
                print("Digite um número válido.")
                continue

            match opcao:
                case 0:
                    exit_db(con)
                    print("Saindo do NEXUS-BIO CMD...")
                    print("Preparando explosivos...")
                    break

                case 1:
                    arquivo = input("Caminho do arquivo SQL: ").strip()
                    create_tables(arquivo, con)

                case 2:
                    drop_tables(con)

                case 3:
                    n = input("Quantas linhas por tabela? [padrão=10]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 10
                    populate_all_tables_ordered(con, n_linhas=n)
                    update_foreign_keys(con)

                case 4:
                    show_table(con)

                case 5:
                    tabela = input("Tabela para atualizar: ").strip()
                    n = input("Quantas linhas aleatórias? [padrão=5]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 5
                    update_random_rows(con, tabela_nome=tabela, n_linhas=n)

                case 6:
                    tabela = input("Tabela para deletar linhas: ").strip()
                    n = input("Quantas linhas aleatórias? [padrão=5]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 5
                    delete_random_rows(con, tabela_nome=tabela, n_linhas=n)

                case 7:
                    update_by_user(con)

                case 8:
                    delete_by_user(con)
                
                case 9:
                    prompt_usuario = input("Digite sua consulta SQL: ").strip()
                    db_schema = get_schema_info(con)
                    query = generate_sql_query(prompt_usuario, db_schema)
                    print(f"Query gerada: {query}")
                    make_query(con, query)
                
                case 10:
                    caminho_imagem = input("Caminho da imagem para busca: ").strip()
                    try:
                        with open(caminho_imagem, "rb") as f:
                            imagem_bytes = f.read()
                        search_similarity(con, imagem_consulta_bytes=imagem_bytes)
                    except FileNotFoundError:
                        print(f"Arquivo '{caminho_imagem}' não encontrado.")
                    except OSError as e:
                        print(f"Erro ao processar a imagem: {e}")
                        
                case 255:
                    print("\nIniciando CRUD completo...")
                    crud(con)

                case _:
                    print("Opção inválida. Tente novamente.")

    except mysql.connector.Error as err:
        print("Erro na conexão com o banco de dados!", err)
