# pip install mysql-connector
# pip install openai
# Cria Uma VENV para executar
# Mude os dados da conexão com o MySQL

import openai
import mysql.connector
from mysql.connector import errorcode
from collections import defaultdict, deque
import re
import ast

openai.api_key = "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"


def connect_mysql(host="localhost", user="root", password="", database=None, port=3306):
    try:
        cnx = mysql.connector.connect(
            host=host, user=user, password=password, database=database, port=port
        )

        if cnx.is_connected():
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
    campos_str = "\n".join(
        f"- `{col['nome']}`: {col['tipo']}" for col in schema[tabela_alvo]
    )

    prompt = f"""
        Gere {n_linhas} linhas de dados realistas e coerentes para a tabela `{tabela_alvo}`, com base no seguinte schema:

        {campos_str}

        As respostas devem estar no formato de uma lista Python com tuplas correspondentes a cada linha de inserção.

        Exemplo de saída:
        [
        (valor1, valor2, ...),
        (valor1, valor2, ...),
        ...
        ]
    """
    return prompt.strip()


def generate_data(prompt, modelo="gpt-4o-mini", temperatura=0.4):
    # Gera dados usando o modelo OpenAI
    response = openai.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperatura,
    )
    return response.choices[0].message.content


def insert_data(conexao, nome_tabela, campos, dados):
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


def exit_db(connect):
    try:
        if connect.is_connected():
            connect.close()
            print("Conexão com o banco de dados foi encerrada!")
        else:
            print("A conexão já estava encerrada.")
    except mysql.connector.Error as err:
        print(f"Erro ao encerrar a conexão: {err}")


""" Mantive só pra lembrar o que é CRUD
    def crud(connect):
        drop_all_tables(connect)
        create_all_tables(connect)
        insert_test(connect)

        print("\n---CONSULTAS BEFORE---")
        consulta1(connect)
        consulta2(connect)
        consulta3(connect)
        consulta_extra(connect)

        update_test(connect)
        delete_test(connect)

        print("\n---CONSULTAS AFTER---")
        consulta1(connect)
        consulta2(connect)
        consulta3(connect)
        consulta_extra(connect) 
"""


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
                --- MENU ---
                1.  Criar tabelas a partir de arquivo SQL
                2.  Deletar todas as tabelas
                3.  Popular todas as tabelas automaticamente (IA)
                4.  Mostrar dados de uma tabela
                5.  Atualizar linhas aleatórias (IA)
                6.  Deletar linhas aleatórias
                7.  Atualizar valor manualmente
                8.  Deletar linhas manualmente
                0.  Sair
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
                    print("Muito obrigado(a).")
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

                case _:
                    print("Opção inválida. Tente novamente.")

    except mysql.connector.Error as err:
        print("Erro na conexão com o banco de dados!", err)
