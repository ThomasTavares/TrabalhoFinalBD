# pip install mysql-connector-python openai pillow transformers torch scikit-learn requests
# Se possível usar VENV (virtualenv) para isolar as dependências do projeto
# Mude os dados da conexão com o MySQL (para usar o banco de dados local)

import re
import ast
import io
import time
import random
from collections import defaultdict, deque
from urllib.parse import quote

import openai
import mysql.connector
from mysql.connector import errorcode
import requests

from PIL import Image, ImageDraw, ImageFont
import numpy as np

from sklearn.metrics.pairwise import cosine_similarity
from transformers import CLIPProcessor, CLIPModel
import torch

# Carrega o modelo e o processador CLIP
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch16")
clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch16")


def get_openai_key():
    """
    Obtém a chave de API da OpenAI do ambiente ou de um arquivo de configuração.
    Retorna:
        str: Chave de API da OpenAI.
    """
    api_key_file = "C:\\Users\\thoma\\Documents\\GitHub\\openai_key.txt"  # Altere para o caminho do seu arquivo de chave
    with open(api_key_file, "r", encoding="utf-8") as f:
        api_key_value = f.read()
    return api_key_value


openai.api_key = get_openai_key()


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


def build_prompt_for_media_table(schema: dict, tabela_alvo: str, n_linhas=20):
    """
    Gera um prompt específico para tabelas que contêm campos BLOB (como Midia).
    Para campos BLOB, sugere usar None ou placeholder, pois a IA não pode gerar dados binários.
    """
    if tabela_alvo.lower() != 'midia':
        return build_prompt(schema, tabela_alvo, n_linhas)
    
    campos_info = []
    for col in schema[tabela_alvo]:
        if 'blob' in col['tipo'].lower():
            campos_info.append(f"- `{col['nome']}`: {col['tipo']} (use None - dados binários serão inseridos separadamente)")
        else:
            campos_info.append(f"- `{col['nome']}`: {col['tipo']}")
    
    campos_str = "\n".join(campos_info)
    
    prompt = f"""
    Gere exatamente {n_linhas} linhas de dados realistas para a tabela `{tabela_alvo}`:
    
    {campos_str}
    
    IMPORTANTE: Para campos BLOB (Dado), use None pois não é possível gerar dados binários.
    
    Formato da resposta:
    [
        (valor1, valor2, None),
        (valor1, valor2, None),
        ...
    ]
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
    insert_query = f"INSERT INTO `{nome_tabela}` ({campos_sql}) VALUES ({placeholders})"
    for linha in dados:
        try:
            cursor.execute(insert_query, linha)
        except mysql.connector.Error as err:
            print(f"Erro ao inserir na tabela `{nome_tabela}`: {err}")

    conexao.commit()
    cursor.close()


def search_image_web(nome_especie, timeout=10):
    """
    Busca uma imagem na web baseada no nome da espécie.
    Parâmetros:
        nome_especie (str): Nome da espécie para buscar imagem.
        timeout (int): Timeout para a requisição HTTP.
    Retorna:
        bytes ou None: Bytes da imagem se encontrada, None caso contrário.
    """
    try:
        # Usando Lorem Picsum com seed baseada no nome da espécie para consistência
        seed = hash(nome_especie) % 1000
        url = f"https://picsum.photos/400/300?random={seed}"
        
        response = requests.get(url, timeout=timeout)
        if response.status_code == 200:
            return response.content
            
    except Exception as e:
        print(f"Erro ao buscar imagem para '{nome_especie}': {e}")
    
    return None


def create_placeholder_image(nome_especie, tamanho=(400, 300)):
    """
    Cria uma imagem placeholder com o nome da espécie.
    Parâmetros:
        nome_especie (str): Nome da espécie.
        tamanho (tuple): Dimensões da imagem (largura, altura).
    Retorna:
        bytes: Bytes da imagem PNG gerada.
    """
    try:
        # Cria uma imagem com cor baseada no hash do nome
        cor_base = hash(nome_especie) % 0xFFFFFF
        cor_rgb = ((cor_base >> 16) & 255, (cor_base >> 8) & 255, cor_base & 255)
        
        # Torna a cor mais suave
        cor_rgb = tuple(min(255, max(50, c + 100)) for c in cor_rgb)
        
        img = Image.new('RGB', tamanho, color=cor_rgb)
        draw = ImageDraw.Draw(img)
        
        # Adiciona texto com o nome da espécie
        try:
            # Tenta usar uma fonte do sistema
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except:
            # Fallback para fonte padrão
            font = ImageFont.load_default()
        
        # Calcula posição central do texto
        bbox = draw.textbbox((0, 0), nome_especie, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (tamanho[0] - text_width) // 2
        y = (tamanho[1] - text_height) // 2
        
        # Desenha o texto
        draw.text((x, y), nome_especie, fill='white', font=font)
        
        # Converte para bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()
        
    except Exception as e:
        print(f"Erro ao criar placeholder para '{nome_especie}': {e}")
        return None


def populate_midia_table(conexao, delay_entre_requisicoes=2):
    """
    Popula a tabela Midia com imagens buscadas automaticamente na web
    baseadas nos nomes das espécies cadastradas no banco.
    
    Parâmetros:
        conexao: Conexão com o banco de dados.
        delay_entre_requisicoes (int): Tempo de espera entre requisições web (em segundos).
    """
    cursor = conexao.cursor()
    
    try:
        # Verifica se a tabela Midia já tem dados
        cursor.execute("SELECT COUNT(*) FROM Midia")
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"Tabela Midia já contém {count} registros. Pulando...")
            return
        
        # Busca todas as espécies cadastradas
        cursor.execute("SELECT ID_Esp, Nome FROM Especie")
        especies = cursor.fetchall()
        
        if not especies:
            print("Nenhuma espécie encontrada. Popule a tabela Especie primeiro.")
            return
        
        print(f"Encontradas {len(especies)} espécies. Buscando imagens...")
        
        sucessos = 0
        falhas = 0
        
        for idx, (id_esp, nome_especie) in enumerate(especies, 1):
            print(f"[{idx}/{len(especies)}] Processando: {nome_especie}")
            
            # Primeiro tenta buscar imagem real na web
            imagem_bytes = search_image_web(nome_especie)
            
            # Se não conseguir, cria um placeholder personalizado
            if not imagem_bytes:
                print(f"  → Criando placeholder para '{nome_especie}'")
                imagem_bytes = create_placeholder_image(nome_especie)
            else:
                print(f"  → Imagem encontrada na web para '{nome_especie}'")
            
            if imagem_bytes:
                try:
                    # Busca um espécime desta espécie para associar à mídia
                    cursor.execute(
                        "SELECT ID_Especime FROM Especime WHERE ID_Esp = %s LIMIT 1",
                        (id_esp,)
                    )
                    especime = cursor.fetchone()
                    
                    if especime:
                        id_especime = especime[0]
                        # Insere na tabela Midia (ID_Midia é AUTO_INCREMENT)
                        cursor.execute(
                            "INSERT INTO Midia (ID_Especime, Tipo, Dado) VALUES (%s, %s, %s)",
                            (id_especime, f"Imagem - {nome_especie}", imagem_bytes)
                        )
                        
                        # Pega o ID da mídia inserida
                        id_midia = cursor.lastrowid
                        
                        sucessos += 1
                        print(f"Sucesso! ID_Midia: {id_midia}")
                    else:
                        print(f"Nenhum espécime encontrado para '{nome_especie}'")
                        falhas += 1
                    
                except mysql.connector.Error as e:
                    print(f"Erro ao inserir mídia para '{nome_especie}': {e}")
                    falhas += 1
            else:
                print(f"Não foi possível obter imagem para '{nome_especie}'")
                falhas += 1
            
            # Delay para não sobrecarregar APIs
            if idx < len(especies):  # Não faz delay na última iteração
                time.sleep(delay_entre_requisicoes)
        
        conexao.commit()
        print(f"\nProcessamento da tabela Midia concluído:")
        print(f"   • Sucessos: {sucessos}")
        print(f"   • Falhas: {falhas}")
        print(f"   • Total processado: {len(especies)}")
        
    except Exception as e:
        print(f"Erro geral ao popular tabela Midia: {e}")
        conexao.rollback()
    finally:
        cursor.close()


def populate_media_table_with_placeholder_images(conexao, n_linhas=10):
    """
    Popula a tabela Midia com imagens placeholder simples (versão antiga).
    """
    # Criar uma imagem placeholder simples
    placeholder_image = Image.new('RGB', (100, 100), color='lightgray')
    img_buffer = io.BytesIO()
    placeholder_image.save(img_buffer, format='JPEG')
    placeholder_bytes = img_buffer.getvalue()
    
    cursor = conexao.cursor()
    
    # Verificar se há especimes disponíveis
    cursor.execute("SELECT ID_Especime FROM Especime")
    especimes = [row[0] for row in cursor.fetchall()]
    
    if not especimes:
        print("Nenhum espécime encontrado. Crie espécimes primeiro.")
        cursor.close()
        return
    
    # Gerar dados para Midia
    tipos_midia = ['Fotografia', 'Microscopia', 'Radiografia', 'Ultrassom']
    
    dados_midia = []
    for i in range(n_linhas):
        id_especime = random.choice(especimes)
        tipo = random.choice(tipos_midia)
        dados_midia.append((id_especime, tipo, placeholder_bytes))
    
    # Inserir na tabela
    insert_query = "INSERT INTO Midia (ID_Especime, Tipo, Dado) VALUES (%s, %s, %s)"
    for linha in dados_midia:
        try:
            cursor.execute(insert_query, linha)
        except mysql.connector.Error as err:
            print(f"Erro ao inserir mídia: {err}")
    
    conexao.commit()
    cursor.close()
    print(f"Tabela Midia populada com {n_linhas} registros e imagens placeholder.")
    

def populate_all_tables(conexao, n_linhas=10):
    """
    Popula todas as tabelas do banco de dados na ordem correta considerando dependências de chaves estrangeiras.
    Primeiro, obtém o schema das tabelas e as dependências de chaves estrangeiras. Em seguida, realiza uma ordenação topológica para determinar a ordem de inserção dos dados, garantindo que tabelas dependentes sejam populadas após suas referências. Para cada tabela, verifica se já possui registros e, caso contrário, gera dados fictícios (sem as colunas de chave estrangeira) e insere na tabela. Ignora tabelas já populadas e trata erros de formatação dos dados gerados.
    Parâmetros:
        conexao: objeto de conexão com o banco de dados.
        n_linhas (int): número de linhas a serem inseridas em cada tabela (padrão: 10).
    """
    
    # Pega o schema e as dependências de chaves estrangeiras
    schema = get_schema_info(conexao)
    ordem = ["Taxon", "Hierarquia", "Especie", "Especime", 
            "Local_de_Coleta", "Amostra", "Midia", "Projeto", 
            "Artigo", "Funcionario", "Proj_Func", "Proj_Esp", 
            "Categoria", "Esp_Cat", "Laboratorio", "Contrato", 
            "Financiador", "Financiamento", "Equipamento", 
            "Registro_de_Uso"]
    
    cursor = conexao.cursor()
    cursor.execute("SHOW TABLES")
    tabelas = [linha[0] for linha in cursor.fetchall()]
    cursor.close()
    valores = [tabela for tabela in ordem if tabela in tabelas]

    # Popular com força
    for tabela_nome in valores:
        print(f"\nTabela: `{tabela_nome}`")
        try:
            cursor = conexao.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_nome}`")
            total = cursor.fetchone()[0]
            cursor.close()
            
            if total > 0:
                print(f"Tabela `{tabela_nome}` já contém {total} registros. Ignorando.")
                continue

            # Tratamento especial para tabela Midia (contém BLOB)
            if tabela_nome.lower() == 'midia':
                populate_midia_table(conexao)
                continue

            campos = [col["nome"] for col in schema[tabela_nome]]

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

            insert_data(conexao, tabela_nome, campos, dados)
            print(f"Populada `{tabela_nome}` com sucesso.")
        except ValueError as e:
            print(f"Erro ao processar `{tabela_nome}`: {e}")


def insert_by_user(conexao):
    """
    Solicita ao usuário o nome da tabela, os campos e valores a serem inseridos, e realiza a operação.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    """
    cursor = conexao.cursor()

    # Exibe tabelas disponíveis
    cursor.execute("SHOW TABLES;")
    tabelas = [t[0] for t in cursor.fetchall()]
    if not tabelas:
        print("Nenhuma tabela encontrada.")
        return

    print("\nTabelas disponíveis:", ", ".join(tabelas))
    tabela_nome = input("Tabela: ").strip()
    if tabela_nome not in tabelas:
        print(f"Tabela `{tabela_nome}` não encontrada.")
        return

    # Exibe colunas da tabela
    cursor.execute(f"DESCRIBE `{tabela_nome}`")
    colunas = [col[0] for col in cursor.fetchall()]
    print("\nColunas disponíveis:", ", ".join(colunas))

    # Solicita campos e valores
    campos = input("Campos (separados por vírgula): ").strip().split(",")
    campos = [c.strip() for c in campos if c.strip() in colunas]
    if not campos:
        print("Nenhum campo válido informado.")
        return

    valores = [input(f"Valor para `{campo}`: ").strip() for campo in campos]

    # Insere os dados
    insert_data(conexao, tabela_nome, campos, [tuple(valores)])
    print("Dados inseridos com sucesso.")


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
    print("\n--- TABELAS DISPONÍVEIS ---")
    cursor = conexao.cursor()

    # Mostra todas as tabelas
    cursor.execute("SHOW TABLES;")
    resultado = cursor.fetchall()

    if not resultado:
        print("Nenhuma tabela encontrada.")
        return

    tabelas = {t[0].lower(): t[0] for t in resultado}
    
    # Obtém o schema de todas as tabelas no banco de dados
    schema = {}
    cursor.execute("SHOW TABLES")
    tabelas = [linha[0] for linha in cursor.fetchall()]

    # Para cada tabela, obtém as colunas e seus tipos
    for tabela_nome in tabelas:
        cursor.execute(f"DESCRIBE `{tabela_nome}`")
        colunas = cursor.fetchall()
        schema[tabela_nome] = [{"nome": col[0], "tipo": col[1]} for col in colunas]
        
    for tabela_nome, colunas in schema.items():
        print(f"\nTabela: {tabela_nome}")
        print("Colunas:")
        for coluna in colunas:
            print(f"  - {coluna['nome']} ({coluna['tipo']})")
    
    tabela_nome = input("Tabela: ").strip()
    
    if schema[tabela_nome] is None:
        print(f"Tabela `{tabela_nome}` não encontrada.")
        return
    
    cursor.execute(f"SELECT COUNT(*) FROM `{tabela_nome}`")
    total = cursor.fetchone()[0]
    if total == 0:
        print(f"A tabela '{tabela_nome}' está vazia.")
        cursor.close()
        return
    
    cursor.close()

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


def crud(conexao):
    # Exemplo de CRUD completo usando as funções já implementadas
    
    # 1. Criar todas as tabelas
    print("\n[CRUD] Criando todas as tabelas a partir de 'script.sql'...")
    create_tables("script.sql", conexao)

    # 1. Deletar todas as tabelas (limpa o banco)
    print("\n[CRUD] Deletando todas as tabelas...")
    drop_tables(conexao)

    # 2. Criar todas as tabelas a partir do arquivo script.sql
    print("\n[CRUD] Criando tabelas a partir de 'script.sql'...")
    create_tables("script.sql", conexao)

    # 3. Popular todas as tabelas automaticamente com dados gerados por IA
    print("\n[CRUD] Populando tabelas automaticamente...")
    populate_all_tables(conexao, n_linhas=10)

    # 4. Mostrar dados de todas as tabelas
    print("\n[CRUD] Exibindo dados de todas as tabelas:")
    schema = get_schema_info(conexao)
    for tabela_nome in schema:
        print(f"\n--- {tabela_nome} ---")
        cursor = conexao.cursor()
        cursor.execute(f"SELECT * FROM `{tabela_nome}`")
        linhas = cursor.fetchall()
        for linha in linhas:
            print(linha)
        cursor.close()

    # 5. Atualizar algumas linhas aleatórias de uma tabela (exemplo: primeira tabela)
    tabela_exemplo = next(iter(schema))
    print(f"\n[CRUD] Atualizando 3 linhas aleatórias da tabela '{tabela_exemplo}'...")
    update_random_rows(conexao, tabela_nome=tabela_exemplo, n_linhas=3)

    # 6. Deletar algumas linhas aleatórias da mesma tabela
    print(f"\n[CRUD] Deletando 2 linhas aleatórias da tabela '{tabela_exemplo}'...")
    delete_random_rows(conexao, tabela_nome=tabela_exemplo, n_linhas=2)

    # 7. Atualização manual (exemplo)
    print(f"\n[CRUD] Atualização manual na tabela '{tabela_exemplo}' (exemplo)...")
    # update_by_user(conexao) 

    # 8. Deleção manual (exemplo)
    print(f"\n[CRUD] Deleção manual na tabela '{tabela_exemplo}' (exemplo)...")
    # delete_by_user(conexao)  

    print("\n[CRUD] CRUD automatizado finalizado.")


if __name__ == "__main__":
    try:
        con = connect_mysql(host="localhost", user="root", password="mysql", database="trabalho_final")

        if not con:
            print("Não foi possível conectar ao banco de dados.")
            exit(1)

        while True:
            print(
                """
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
                ║ [  8 ] > IA: Atualizar Dados Aleatórios     ║
                ║ [  9 ] > IA: Gerar SQL a partir de Texto    ║
                ║ [ 10 ] > IA: Buscar Imagens Similares       ║
                ║ [ 11 ] > Executar CRUD Automático           ║
                ║ [ 12 ] > Remover Dados Aleatórios           ║
                ║ [  0 ] > Explodir Sistema                   ║
                ╚═════════════════════════════════════════════╝
                """
            )

            try:
                opcao = int(input("Opção: ").strip())
                if opcao < -1 or opcao > 11:
                    print("Opção inválida. Escolha um número válido")
            except ValueError:
                print("Entrada inválida. Por favor, digite um número.")
                opcao = None

            if opcao is None or opcao < -1 or opcao > 11:
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
                    show_table(con)

                case 4:
                    insert_by_user(con)

                case 5:
                    update_by_user(con)

                case 6:
                    delete_by_user(con)

                case 7:
                    n = input("Quantas linhas por tabela? [padrão=10]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 10
                    populate_all_tables(con, n_linhas=n)

                case 8:
                    tabela = input("Tabela para atualizar: ").strip()
                    n = input("Quantas linhas aleatórias? [padrão=5]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 5
                    update_random_rows(con, tabela_nome=tabela, n_linhas=n)

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
                
                case 11:
                    print("\nIniciando CRUD Automático...")
                    crud(con)
                    
                case 12:
                    tabela = input("Tabela para deletar linhas: ").strip()
                    n = input("Quantas linhas aleatórias? [padrão=5]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 5
                    delete_random_rows(con, tabela_nome=tabela, n_linhas=n)

                case _:
                    print("Opção inválida. Tente novamente.")

    except mysql.connector.Error as err:
        print("Erro na conexão com o banco de dados!", err)