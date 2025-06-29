# pip install mysql-connector-python openai pillow transformers torch scikit-learn requests prettytable
# Se possível usar VENV (virtualenv) para isolar as dependências do projeto
# Mude os dados da conexão com o MySQL (para usar o banco de dados local)

import re
import ast
import io
import time
import random
import json
from datetime import datetime
from prettytable import PrettyTable
from collections import defaultdict, deque
from urllib.parse import quote

import openai
import mysql.connector
from mysql.connector import errorcode
import requests

from PIL import Image, ImageDraw, ImageFont
import numpy as np

from sklearn.metrics.pairwise import cosine_similarity

# Imports condicionais para funcionalidades avançadas
try:
    from transformers import CLIPProcessor, CLIPModel
    import torch
    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False
    print("CLIP não disponível - funcionalidades de similaridade de imagem desabilitadas")

# Carrega o modelo e o processador CLIP apenas quando necessário (lazy loading)
clip_model = None
clip_processor = None

def load_clip_model():
    """Carrega o modelo CLIP apenas quando necessário"""
    global clip_model, clip_processor
    if not CLIP_AVAILABLE:
        print("CLIP não está disponível")
        return False
        
    if clip_model is None:
        print("Carregando modelo CLIP...")
        try:
            clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch16")
            clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch16", use_fast=True)
            print("Modelo CLIP carregado com sucesso!")
            return True
        except (OSError, ValueError, RuntimeError) as e:
            print(f"Erro ao carregar CLIP: {e}")
            return False
    return True


def get_openai_key():
    """
    Obtém a chave de API da OpenAI do ambiente ou de um arquivo de configuração.
    Retorna:
        str: Chave de API da OpenAI.
    """
    # api_key_file = "/home/samuks369/Downloads/gpt-key.txt"
    api_key_file = "C:\\Users\\thoma\\Documents\\GitHub\\openai_key.txt"
    try:
        with open(api_key_file, "r", encoding="utf-8") as f:
            api_key_value = f.read().strip()  # Remove quebras de linha e espaços
        return api_key_value
    except FileNotFoundError:
        print(f"Arquivo de chave não encontrado: {api_key_file}")
        return None
    except FileNotFoundError as e:
        print(f"Arquivo de chave não encontrado: {e}")
        return None
    except IOError as e:
        print(f"Erro de entrada/saída ao ler chave API: {e}")
        return None

api_key = get_openai_key()
if api_key:
    openai.api_key = api_key
else:
    print("Chave OpenAI não configurada - funcionalidades de IA podem não funcionar")


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
    
    # Verifica se a API key está configurada
    if not openai.api_key:
        print("Chave OpenAI não configurada")
        return None
    
    try:
        # Gera dados usando o modelo OpenAI
        response = openai.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperatura,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Erro na API OpenAI: {e}")
        return None


def build_prompt(schema: dict, tabela_alvo: str, n_linhas: int, contexto_dados: dict, foreign_keys_data: dict):
    """
    Constrói um prompt extremamente detalhado e rigoroso para a IA gerar dados válidos para uma tabela específica.
    Versão melhorada com constraints rigorosas baseadas no script.sql.
    """
    with open("script.sql", "r", encoding="utf-8") as f:
        script = f.read()
    
    # Definições específicas e rigorosas de constraints baseadas no script.sql
    constraints_rigidas = {
        'taxon': {
            'Tipo': "OBRIGATÓRIO: EXATAMENTE um dos valores: 'Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero'",
            'Nome': "VARCHAR(50) - Nomes taxonômicos científicos reais e válidos",
            'validacao': "- Dominio: Eukarya\n- Reino: Animalia, Plantae, Fungi\n- Criar hierarquia taxonômica coerente\n- Combinação (Tipo, Nome) deve ser única"
        },
        'especie': {
            'IUCN': "OBRIGATÓRIO: EXATAMENTE um dos códigos: 'LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX'",
            'Nome': "VARCHAR(50) - Nome científico binomial (Gênero espécie) - deve ser real",
            'Nome_Pop': "VARCHAR(50) - Nome popular em português brasileiro",
            'ID_Gen': "FK obrigatória - DEVE referenciar Taxon com Tipo='Genero'",
            'validacao': "- Nome binomial científico correto\n- IUCN mais comum: LC (Least Concern)\n- Descrição biológica realista max 500 chars"
        },
        'projeto': {
            'Status': "OBRIGATÓRIO: EXATAMENTE um dos valores: 'Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado'",
            'Nome': "VARCHAR(50) - Nomes de projetos científicos realistas",
            'Descricao': "VARCHAR(100) - Descrição concisa do projeto",
            'validacao': "- Status mais comum: 'Ativo'\n- Dt_Inicio anterior a Dt_Fim\n- Datas realistas (2020-2025)"
        },
        'contrato': {
            'Status': "OBRIGATÓRIO: EXATAMENTE um dos valores: 'Pendente', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado'",
            'Valor': "DECIMAL(10,2) - Valor monetário positivo (salários brasileiros realistas)",
            'validacao': "- Status mais comum: 'Ativo'\n- Valores entre 3000.00 e 25000.00 reais\n- Dt_Inicio anterior a Dt_Fim"
        },
        'funcionario': {
            'CPF': "VARCHAR(11) - EXATAMENTE 11 dígitos numéricos (sem pontos/traços)",
            'Nome': "VARCHAR(50) - Nomes brasileiros realistas",
            'Cargo': "VARCHAR(50) - Cargos acadêmicos/científicos válidos",
            'validacao': "- CPF: apenas números, 11 dígitos\n- Cargos: Pesquisador, Professor, Técnico, Estagiário, Bolsista"
        },
        'artigo': {
            'DOI': "VARCHAR(50) - Formato DOI válido: '10.xxxx/xxxxx'",
            'Titulo': "VARCHAR(50) - Título científico realista",
            'Resumo': "VARCHAR(2500) - Resumo científico detalhado",
            'validacao': "- DOI formato: 10.1234/exemplo.2023\n- Títulos acadêmicos realistas\n- Link de revistas científicas"
        }
    }
    
    # Contexto geral mais específico
    contexto_banco = """
    CONTEXTO RIGOROSO DO SISTEMA:
    Sistema de laboratório de taxonomia científica que DEVE seguir padrões acadêmicos reais:
    - Taxonomia: Dominio → Reino → Filo → Classe → Ordem → Familia → Genero → Especie
    - Espécies com nomes científicos binomiais REAIS
    - Projetos, artigos e funcionários de ambiente acadêmico brasileiro
    - Status e códigos IUCN oficiais
    - Valores monetários em reais (Brasil)
    """
    
    # Informações detalhadas da tabela atual
    if tabela_alvo in schema:
        campos_info = []
        constraints_tabela = constraints_rigidas.get(tabela_alvo.lower(), {})
        
        for col in schema[tabela_alvo]:
            tipo_col = col['tipo']
            nome_col = col['nome']
            
            if 'blob' in tipo_col.lower():
                campos_info.append(f"- {nome_col}: {tipo_col} (SEMPRE null no JSON)")
            else:
                # Adiciona constraint específica se existir
                constraint_info = constraints_tabela.get(nome_col, f"{tipo_col} - valor apropriado")
                campos_info.append(f"- {nome_col}: {constraint_info}")
        
        campos_str = "\n".join(campos_info)
        
        # Adiciona validação extra se existir
        validacao_extra = constraints_tabela.get('validacao', '')
        if validacao_extra:
            campos_str += f"\n\nVALIDAÇÕES EXTRAS:\n{validacao_extra}"
    else:
        campos_str = "ERRO: Tabela não encontrada no schema"
    
    # Contexto com dados já existentes (mais detalhado)
    contexto_existente = ""
    if contexto_dados:
        contexto_existente = "\n\nDADOS EXISTENTES (use para manter consistência):\n"
        for tabela, registros in contexto_dados.items():
            contexto_existente += f"\n{tabela.upper()} (exemplo):\n"
            for i, registro in enumerate(registros[:2]):  # Apenas 2 exemplos
                contexto_existente += f"  {registro}\n"
    
    # Chaves estrangeiras mais detalhadas
    fk_info = ""
    if foreign_keys_data:
        fk_info = "\n\nCHAVES ESTRANGEIRAS OBRIGATÓRIAS (use SOMENTE estes IDs):\n"
        for campo, valores in foreign_keys_data.items():
            fk_info += f"\n{campo} - IDs válidos:\n"
            for valor in valores[:8]:  # Mostra 8 opções
                if len(valor) >= 2:
                    fk_info += f"  ID {valor[0]}: {valor[1]}\n"
                else:
                    fk_info += f"  ID {valor[0]}\n"
            if len(valores) > 8:
                fk_info += f"  ... e mais {len(valores)-8} opções\n"
    
    # Instruções ultra-específicas por tabela
    instrucoes_ultra_especificas = {
        'hierarquia': 'ID_Tax e ID_TaxTopo DEVEM ser IDs existentes da tabela Taxon. Criar hierarquia: Dominio→Reino→Filo→Classe→Ordem→Familia→Genero.',
        'especie': 'ID_Gen DEVE ser ID de Taxon com Tipo="Genero". Nome DEVE ser binomial real (ex: "Homo sapiens"). IUCN mais comum: "LC".',
        'especime': 'ID_Esp DEVE ser ID existente da tabela Especie. Descritivo: "Adulto macho", "Jovem fêmea", "Espécime preservado".',
        'amostra': 'Use IDs existentes. Tipo: "Sangue", "DNA", "Tecido", "Osso". Data de coleta realista (2020-2024).',
        'artigo': 'ID_Proj DEVE existir. DOI formato: "10.1234/revista.2023.123". Títulos acadêmicos reais.',
        'proj_func': 'Tabela de associação. Use IDs existentes de Projeto e Funcionario. Cada par (ID_Proj, ID_Func) único.',
        'proj_esp': 'Tabela de associação. Use IDs existentes de Projeto e Especie. Cada par único.',
        'proj_cat': 'Tabela de associação. Use IDs existentes de Projeto e Categoria. Cada par único.',
        'contrato': 'Status válidos listados acima. Valor entre 3000.00-25000.00. Datas coerentes.',
        'financiamento': 'Use IDs existentes. Valores realistas para financiamento (10000.00-500000.00).',
        'registro_de_uso': 'Use IDs existentes. Dt_Reg formato timestamp completo com hora atual.'
    }
    
    instrucao_tabela = instrucoes_ultra_especificas.get(tabela_alvo.lower(), 'Gere dados realistas seguindo todas as constraints.')
    
    prompt = f"""
    {contexto_banco}
    
    TABELA ALVO: {tabela_alvo.upper()}
    SCHEMA RIGOROSO (SIGA TODAS AS CONSTRAINTS):
    {campos_str}
    
    {contexto_existente}
    
    {fk_info}
    
    INSTRUÇÕES ESPECÍFICAS PARA {tabela_alvo.upper()}:
    {instrucao_tabela}
    
    TAREFA CRÍTICA:
    Gere EXATAMENTE {n_linhas} registros VÁLIDOS para `{tabela_alvo}`.
    
    REGRAS ABSOLUTAS (VIOLAÇÃO = ERRO):
    1. Use APENAS os valores de Status/IUCN/Tipo listados nas constraints
    2. Use APENAS IDs de FK listados acima
    3. Respeite EXATAMENTE os tamanhos VARCHAR
    4. CPF: apenas 11 dígitos numéricos
    5. DOI: formato 10.xxxx/yyyy
    6. Datas: 'YYYY-MM-DD' válidas
    7. Valores decimais: formato numérico (ex: 15000.50)
    8. BLOB: sempre null
    9. Nomes científicos REAIS e válidos
    10. Consistência com dados existentes
    
    FORMATO OBRIGATÓRIO (JSON válido):
    {{
        "registros": [
            {{"campo1": valor1, "campo2": "valor2"}},
            {{"campo1": valor3, "campo2": "valor4"}}
        ]
    }}
    
    RESPONDA APENAS COM O JSON. NENHUM TEXTO ADICIONAL.
    """
    
    return prompt.strip()


def build_prompt_for_media_table(schema: dict, tabela_alvo: str, n_linhas=20):
    """
    Gera um prompt específico para a tabela Midia (com campos BLOB).
    Esta função garante que campos BLOB sejam sempre null no JSON,
    evitando que a IA tente gerar dados binários aleatórios.
    """
    if tabela_alvo.lower() != 'midia':
        return build_prompt(schema, tabela_alvo, n_linhas, {}, {})
    
    prompt = f"""
    CONTEXTO: Sistema de laboratório de taxonomia - Tabela de mídia para armazenar imagens/áudios de espécimes.
    
    IMPORTANTE: NÃO gere dados para o campo BLOB. Sempre use null.
    
    Gere {n_linhas} registros JSON para a tabela Midia:
    - ID_Midia: integer (sequencial começando em 1)
    - ID_Especime: integer (referência aos espécimes existentes, use valores 1-{min(10, n_linhas)})
    - Tipo: varchar(50) (exemplos: "Fotografia dorsal", "Microscopia 40x", "Áudio de vocalização", "Imagem lateral", "Video comportamental")
    - Dado: blob (SEMPRE null no JSON - as imagens serão inseridas separadamente)
    
    FORMATO DE RESPOSTA:
    {{
        "registros": [
            {{"ID_Midia": 1, "ID_Especime": 1, "Tipo": "Fotografia lateral", "Dado": null}},
            {{"ID_Midia": 2, "ID_Especime": 2, "Tipo": "Microscopia 100x", "Dado": null}},
            ...
        ]
    }}
    
    REGRAS:
    - Varie os tipos de mídia (fotografia, microscopia, áudio, vídeo)
    - IDs sequenciais começando em 1
    - Campo Dado sempre null
    - ID_Especime deve referenciar espécimes existentes
    
    Responda SOMENTE com o JSON, sem explicações.
    """
    return prompt.strip()


def validate_generated_data(registros, tabela_nome, schema):
    """
    Valida e corrige dados gerados pela IA para garantir conformidade com o schema.
    """
    if not registros or not isinstance(registros, list):
        return []
    
    registros_validos = []
    
    # Constraints específicas baseadas no schema SQL
    constraints = {
        'taxon': {
            'Tipo': ['Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero'],
        },
        'especie': {
            'IUCN': ['LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX'],
        },
        'projeto': {
            'Status': ['Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado'],
        },
        'contrato': {
            'Status': ['Pendente', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado'],
        }
    }
    
    tabela_lower = tabela_nome.lower()
    constraint_tabela = constraints.get(tabela_lower, {})
    
    for i, registro in enumerate(registros):
        if not isinstance(registro, dict):
            print(f"  Registro {i+1} ignorado: não é um dicionário")
            continue
        
        registro_corrigido = {}
        registro_valido = True
        
        for campo, valor in registro.items():
            # Valida constraints específicas
            if campo in constraint_tabela:
                valores_validos = constraint_tabela[campo]
                if valor not in valores_validos:
                    # Corrige com valor padrão
                    valor_corrigido = valores_validos[0] if valores_validos else valor
                    print(f"  Corrigindo {campo}: '{valor}' → '{valor_corrigido}'")
                    valor = valor_corrigido
            
            # Valida CPF (deve ter exatamente 11 dígitos)
            if campo == 'CPF' and valor:
                cpf_limpo = re.sub(r'\D', '', str(valor))
                if len(cpf_limpo) != 11:
                    # Gera CPF válido simples
                    cpf_limpo = ''.join([str(random.randint(0, 9)) for _ in range(11)])
                    print(f"  Corrigindo CPF inválido: {valor} → {cpf_limpo}")
                valor = cpf_limpo
            
            # Valida DOI
            if campo == 'DOI' and valor:
                if not re.match(r'^10\.\d+/.+', str(valor)):
                    valor = f"10.{random.randint(1000, 9999)}/example.{random.randint(2020, 2024)}.{random.randint(1, 999)}"
                    print(f"  Corrigindo DOI: formato inválido → {valor}")
            
            # Valida datas
            if 'data' in campo.lower() or 'dt_' in campo.lower():
                if valor and not re.match(r'^\d{4}-\d{2}-\d{2}', str(valor)):
                    valor = f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
                    print(f"  Corrigindo data em {campo}: formato inválido → {valor}")
            
            # Valida valores decimais/monetários
            if campo in ['Valor'] and valor:
                try:
                    valor_float = float(valor)
                    if valor_float <= 0:
                        valor = round(random.uniform(3000.0, 25000.0), 2)
                        print(f"  Corrigindo valor monetário: {valor_float} → {valor}")
                    else:
                        valor = round(valor_float, 2)
                except (ValueError, TypeError):
                    valor = round(random.uniform(3000.0, 25000.0), 2)
                    print(f"  Corrigindo valor não numérico → {valor}")
            
            registro_corrigido[campo] = valor
        
        if registro_valido and registro_corrigido:
            registros_validos.append(registro_corrigido)
    
    print(f"  Validação: {len(registros_validos)}/{len(registros)} registros válidos")
    return registros_validos


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


def clean_json_response(response):
    """
    Limpa a resposta da IA removendo blocos de código markdown e outros caracteres indesejados.
    """
    if not response:
        return response
    
    # Remove blocos de código markdown
    response = re.sub(r'```json\s*', '', response)
    response = re.sub(r'```\s*', '', response)
    
    # Remove texto antes e depois do JSON
    lines = response.split('\n')
    start_idx = -1
    end_idx = -1
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped.startswith('{'):
            start_idx = i
            break
    
    for i in range(len(lines) - 1, -1, -1):
        line_stripped = lines[i].strip()
        if line_stripped.endswith('}'):
            end_idx = i
            break
    
    if start_idx != -1 and end_idx != -1:
        json_lines = lines[start_idx:end_idx + 1]
        return '\n'.join(json_lines)
    
    return response.strip()


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
            
    except requests.RequestException as e:
        print(f"Erro de requisição ao buscar imagem para '{nome_especie}': {e}")
    except ValueError as e:
        print(f"Erro de valor ao buscar imagem para '{nome_especie}': {e}")
    except IOError as e:
        print(f"Erro de entrada/saída ao buscar imagem para '{nome_especie}': {e}")
    
    return None


def search_image_web_improved(nome_especie, timeout=10):
    """
    Versão melhorada para buscar imagens mais relevantes para espécies.
    Tenta diferentes APIs e fontes de imagem.
    """
    try:
        # Limpa o nome da espécie para usar como parâmetro
        nome_limpo = re.sub(r'[^a-zA-Z\s]', '', nome_especie).strip()
        
        # Tenta diferentes estratégias de busca
        urls_tentativas = [
            # Placeholder com tema biológico baseado no hash do nome
            f"https://picsum.photos/400/300?random={abs(hash(nome_especie)) % 1000}",
            # Backup com seed diferente
            f"https://picsum.photos/450/350?random={abs(hash(nome_especie + 'bio')) % 1000}",
        ]
        
        for i, url in enumerate(urls_tentativas):
            try:
                print(f"      Tentativa {i+1}: {url}")
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200 and len(response.content) > 1000:  # Verifica se é uma imagem válida
                    print(f"Imagem obtida ({len(response.content)} bytes)")
                    return response.content
                else:
                    print(f"Resposta inválida (status: {response.status_code})")
            except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
                print(f"Erro na tentativa {i+1}: {e}")
                continue
                
    except requests.RequestException as e:
        print(f"Erro de requisição ao buscar imagem para '{nome_especie}': {e}")
    except IOError as e:
        print(f"Erro de entrada/saída ao buscar imagem para '{nome_especie}': {e}")
    
    return None


def create_placeholder_image_improved(nome_especie, nome_popular=None, descricao=None, tamanho=(400, 300)):
    """
    Versão melhorada para criar imagem placeholder mais informativa.
    """
    try:
        # Determina cor baseada no tipo de organismo (se disponível na descrição)
        cor_base = hash(nome_especie) % 0xFFFFFF
        
        # Ajusta cor baseada em palavras-chave na descrição
        if descricao:
            desc_lower = descricao.lower()
            if any(palavra in desc_lower for palavra in ['plant', 'planta', 'vegetal', 'flora']):
                cor_base = 0x4CAF50  # Verde para plantas
            elif any(palavra in desc_lower for palavra in ['animal', 'fauna', 'mammal', 'bird']):
                cor_base = 0xFF9800  # Laranja para animais
            elif any(palavra in desc_lower for palavra in ['fungi', 'fungo', 'mushroom']):
                cor_base = 0x8BC34A  # Verde claro para fungos
            elif any(palavra in desc_lower for palavra in ['bacteria', 'microb']):
                cor_base = 0x2196F3  # Azul para microorganismos
        
        cor_rgb = ((cor_base >> 16) & 255, (cor_base >> 8) & 255, cor_base & 255)
        
        # Torna a cor mais suave
        cor_rgb = tuple(min(255, max(50, c + 80)) for c in cor_rgb)
        
        img = Image.new('RGB', tamanho, color=cor_rgb)
        draw = ImageDraw.Draw(img)
        
        # Adiciona bordas decorativas
        border_color = tuple(max(0, c - 40) for c in cor_rgb)
        draw.rectangle([0, 0, tamanho[0]-1, tamanho[1]-1], outline=border_color, width=3)
        
        # Configura fontes
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
            font_subtitle = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except OSError:
            font_title = ImageFont.load_default()
            font_subtitle = ImageFont.load_default()
        
        # Prepara textos
        textos = [nome_especie]
        if nome_popular and nome_popular.strip():
            textos.append(f"({nome_popular})")
        
        # Desenha os textos centralizados
        y_offset = tamanho[1] // 2 - 30
        
        for i, texto in enumerate(textos):
            font = font_title if i == 0 else font_subtitle
            
            # Quebra texto se muito longo
            if len(texto) > 25:
                palavras = texto.split()
                linhas = []
                linha_atual = ""
                for palavra in palavras:
                    if len(linha_atual + palavra) < 25:
                        linha_atual += palavra + " "
                    else:
                        if linha_atual:
                            linhas.append(linha_atual.strip())
                        linha_atual = palavra + " "
                if linha_atual:
                    linhas.append(linha_atual.strip())
            else:
                linhas = [texto]
            
            for linha in linhas:
                bbox = draw.textbbox((0, 0), linha, font=font)
                text_width = bbox[2] - bbox[0]
                x = (tamanho[0] - text_width) // 2
                
                # Sombra do texto
                draw.text((x + 1, y_offset + 1), linha, fill='black', font=font)
                # Texto principal
                draw.text((x, y_offset), linha, fill='white', font=font)
                
                y_offset += 25
        
        # Adiciona ícone simples baseado no tipo
        if descricao:
            desc_lower = descricao.lower()
            icon_y = tamanho[1] - 50
            if 'plant' in desc_lower:
                # Desenha uma folha simples
                draw.ellipse([tamanho[0]//2 - 10, icon_y, tamanho[0]//2 + 10, icon_y + 20], 
                           fill='lightgreen', outline='darkgreen')
            elif 'animal' in desc_lower:
                # Desenha um círculo simples
                draw.ellipse([tamanho[0]//2 - 8, icon_y, tamanho[0]//2 + 8, icon_y + 16], 
                           fill='lightyellow', outline='orange')
        
        # Converte para bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()
        
    except Exception as e:
        print(f"Erro ao criar placeholder melhorado para '{nome_especie}': {e}")
        # Fallback para função simples
        return create_placeholder_image(nome_especie, tamanho)


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
        
    except (OSError, IOError) as e:
        print(f"Erro ao criar placeholder para '{nome_especie}': {e}")
        return None


def populate_all_tables(conexao, n_linhas=10, n_especies=20):
    """
    Versão melhorada que popula todas as tabelas com contexto adequado do banco de dados.
    Mantém o contexto das tabelas já populadas e usa chaves estrangeiras corretas.
    """
    # VERIFICA SE AS TABELAS EXISTEM ANTES DE TENTAR POPULAR
    cursor = conexao.cursor()
    cursor.execute("SHOW TABLES")
    tabelas_banco = cursor.fetchall()
    cursor.close()
    
    if not tabelas_banco:
        print("\n❌ ERRO: Nenhuma tabela encontrada no banco de dados!")
        print("\n💡 SOLUÇÃO: Você precisa criar as tabelas primeiro.")
        resposta = input("\nDeseja criar as tabelas automaticamente agora? (s/N): ").strip().lower()
        
        if resposta in ['s', 'sim', 'y', 'yes']:
            print("\n🔧 Criando tabelas automaticamente...")
            try:
                create_tables(conexao)
                print("✅ Tabelas criadas com sucesso!")
                
                # Atualiza a lista de tabelas existentes
                cursor = conexao.cursor()
                cursor.execute("SHOW TABLES")
                tabelas_banco = cursor.fetchall()
                cursor.close()
                
                if not tabelas_banco:
                    print("❌ Erro: Falha ao criar tabelas. Verifique o arquivo script.sql")
                    return 0, 1
                    
            except Exception as e:
                print(f"❌ Erro ao criar tabelas: {e}")
                return 0, 1
        else:
            print("⚠️  Operação cancelada. Execute a opção 1 (Criar Tabelas) primeiro.")
            return 0, 1
    
    # Cria mapeamento de nomes case-insensitive para nomes reais
    tabelas_existentes = {}
    for (nome_real,) in tabelas_banco:
        tabelas_existentes[nome_real.lower()] = nome_real
    
    print(f"\n📊 Tabelas encontradas no banco: {list(tabelas_existentes.values())}")
    
    schema = get_schema_info(conexao)
    
    # ORDEM CORRETA respeitando dependências de chave estrangeira
    ordem = [
        "taxon",           # Base da taxonomia - não tem dependências
        "hierarquia",      # Depende de taxon
        "especie",         # Depende de taxon (gênero)
        "especime",        # Depende de especie
        "local_de_coleta", # Independente
        "projeto",         # Movido antes para resolver dependências
        "amostra",         # Depende de especie e local_de_coleta
        "funcionario",     # Independente
        "categoria",       # Independente  
        "laboratorio",     # Independente
        "financiador",     # Independente
        "equipamento",     # Independente
        "midia",           # Depende de especime
        "artigo",          # Depende de projeto
        "proj_func",       # Depende de projeto e funcionario
        "proj_esp",        # Depende de projeto e especie
        "proj_cat",        # Depende de projeto e categoria
        "contrato",        # Depende de funcionario e laboratorio
        "financiamento",   # Depende de projeto e financiador
        "registro_de_uso"  # Depende de funcionario e equipamento
    ]
    
    # Filtra apenas tabelas que existem no banco (comparação case-insensitive)
    tabelas_ordenadas = []
    for tabela_ordem in ordem:
        if tabela_ordem in tabelas_existentes:
            tabelas_ordenadas.append(tabelas_existentes[tabela_ordem])  # Usa o nome real da tabela
    
    # Verifica se alguma tabela essencial está faltando
    tabelas_faltando = [t for t in ordem if t not in tabelas_existentes]
    if tabelas_faltando:
        print(f"\n⚠️  AVISO: {len(tabelas_faltando)} tabelas não encontradas no banco:")
        for tabela in tabelas_faltando[:5]:  # Mostra apenas as primeiras 5
            print(f"   - {tabela.upper()}")
        if len(tabelas_faltando) > 5:
            print(f"   ... e mais {len(tabelas_faltando) - 5} tabelas")
        print("\n💡 Considerações:")
        print("   - Essas tabelas podem estar faltando no script.sql")
        print("   - Ou podem ter nomes diferentes do esperado")
        print("   - A população continuará apenas com as tabelas existentes")
        
        continuar = input("\nDeseja continuar mesmo assim? (s/N): ").strip().lower()
        if continuar not in ['s', 'sim', 'y', 'yes']:
            print("⚠️  Operação cancelada pelo usuário.")
            return 0, 1
    
    print(f"\nIniciando população de {len(tabelas_ordenadas)} tabelas...")
    print(f"Ordem de execução: {' → '.join([t.upper() for t in tabelas_ordenadas])}")

    sucessos_totais = 0
    erros_totais = 0
    tabelas_processadas = 0
    tabelas_ja_populadas = []  # Lista para manter contexto das tabelas já processadas

    for tabela_nome in tabelas_ordenadas:
        print(f"\n{'='*70}")
        print(f"Processando tabela: `{tabela_nome.upper()}`")
        
        try:
            # Verifica se a tabela já tem dados
            cursor = conexao.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_nome}`")
            total_existente = cursor.fetchone()[0]
            cursor.close()
            
            if total_existente > 0:
                print(f"Tabela `{tabela_nome.upper()}` já contém {total_existente} registros. Adicionando ao contexto...")
                tabelas_ja_populadas.append(tabela_nome)
                continue
            
            # TRATAMENTO ESPECIAL PARA TABELA TAXON
            if tabela_nome.lower() == 'taxon':
                print("Aplicando tratamento especial para a tabela `Taxon`...")
                resultado = populate_taxon_table(conexao, n_especies)
                if resultado:
                    sucessos_totais += 1
                    tabelas_processadas += 1
                    tabelas_ja_populadas.append(tabela_nome)
                else:
                    erros_totais += 1
                continue

            # TRATAMENTO ESPECIAL PARA TABELA MIDIA  
            if tabela_nome.lower() == 'midia':
                print("Preenchendo tabela `Midia` com imagens reais...")
                resultado = populate_midia_table(conexao)
                if resultado:
                    sucessos_totais += 1
                    tabelas_processadas += 1
                    tabelas_ja_populadas.append(tabela_nome)
                else:
                    erros_totais += 1
                continue

            # VERIFICAÇÃO DE DEPENDÊNCIAS ANTES DE GERAR DADOS
            dependencias_ok = verify_dependencies(conexao, tabela_nome, schema)
            if not dependencias_ok:
                print(f"Pulando `{tabela_nome.upper()}`: dependências não atendidas")
                erros_totais += 1
                continue

            # COLETA O CONTEXTO DAS TABELAS JÁ POPULADAS
            print("Coletando contexto das tabelas já populadas...")
            contexto_dados = get_existing_data_for_context(conexao, tabelas_ja_populadas, limite_por_tabela=5)
            
            # COLETA AS CHAVES ESTRANGEIRAS DISPONÍVEIS
            print("Coletando chaves estrangeiras disponíveis...")
            foreign_keys_data = get_available_foreign_keys(conexao, tabela_nome)
            
            # Log do contexto coletado para debug
            if contexto_dados:
                print(f"Contexto disponível de {len(contexto_dados)} tabelas: {list(contexto_dados.keys())}")
            if foreign_keys_data:
                print(f"Chaves estrangeiras encontradas: {list(foreign_keys_data.keys())}")

            # GERAÇÃO DE DADOS VIA IA PARA OUTRAS TABELAS
            print(f"Gerando {n_linhas} registros via IA com contexto...")
            
            # Ajusta número de linhas baseado nas dependências disponíveis
            n_linhas_ajustado = adjust_row(conexao, tabela_nome, n_linhas)
            
            # Escolhe o prompt adequado COM CONTEXTO
            if tabela_nome.lower() == 'midia':
                prompt = build_prompt_for_media_table(schema, tabela_nome, n_linhas_ajustado)
            else:
                prompt = build_prompt(schema, tabela_nome, n_linhas_ajustado, contexto_dados, foreign_keys_data)
            
            # Gera dados com retry em caso de erro
            resposta = None
            max_tentativas = 3
            
            for tentativa in range(1, max_tentativas + 1):
                try:
                    print(f"Tentativa {tentativa}/{max_tentativas}")
                    resposta = generate_data(prompt)
                    
                    if resposta and resposta.strip():
                        break
                    else:
                        print(f"Resposta vazia na tentativa {tentativa}")
                        
                except Exception as e:  # Mudança aqui - captura qualquer exceção do OpenAI
                    print(f"Erro na tentativa {tentativa}: {e}")
                    if tentativa == max_tentativas:
                        print(f"Falha final após {max_tentativas} tentativas")
                        resposta = None
                        break
                    time.sleep(2)  # Pausa entre tentativas
            
            if not resposta:
                print(f"Falha ao gerar dados para `{tabela_nome.upper()}` após {max_tentativas} tentativas")
                erros_totais += 1
                continue
            
            # Limpa a resposta antes do parse
            resposta_limpa = clean_json_response(resposta)
            
            if not resposta_limpa.strip():
                print(f"Resposta vazia após limpeza para `{tabela_nome.upper()}`")
                print(f"Resposta original: {resposta[:100]}...")
                erros_totais += 1
                continue
            
            try:
                # Parse e validação do JSON
                dados_json = json.loads(resposta_limpa)
                
                if not isinstance(dados_json, dict) or "registros" not in dados_json:
                    print(f"Estrutura JSON inválida para `{tabela_nome.upper()}`")
                    print("Esperado: {{'registros': [...]}}")
                    print(f"Recebido: {str(dados_json)[:100]}...")
                    erros_totais += 1
                    continue
                
                registros = dados_json["registros"]
                if not registros:
                    print(f"Nenhum registro gerado para `{tabela_nome.upper()}`")
                    continue
                
                # Valida estrutura dos registros
                if not validate_structure(registros, schema.get(tabela_nome, [])):
                    print(f"Estrutura de registros inválida para `{tabela_nome.upper()}`")
                    erros_totais += 1
                    continue
                
                # Validação básica de chaves estrangeiras inline
                if foreign_keys_data:
                    print("Validando e corrigindo chaves estrangeiras...")
                    for i, registro in enumerate(registros):
                        for campo_fk, valores_validos in foreign_keys_data.items():
                            if campo_fk in registro:
                                valor_atual = registro[campo_fk]
                                ids_validos = [v[0] for v in valores_validos] if valores_validos else []
                                
                                # Se o valor não é válido, substitui por um aleatório válido
                                if valor_atual not in ids_validos and ids_validos:
                                    novo_valor = random.choice(ids_validos)
                                    print(f"  Corrigindo registro {i+1}: {campo_fk} {valor_atual} → {novo_valor}")
                                    registro[campo_fk] = novo_valor
                
                # Insere os dados
                print(f"Inserindo {len(registros)} registros...")
                resultado_insercao = insert_data_from_json(conexao, tabela_nome, dados_json)
                
                if resultado_insercao is not False:  # Considera sucesso se não retornar False explicitamente
                    print(f"Tabela `{tabela_nome.upper()}` processada com sucesso")
                    sucessos_totais += 1
                    tabelas_processadas += 1
                    tabelas_ja_populadas.append(tabela_nome)  # Adiciona ao contexto para próximas tabelas
                else:
                    print(f"Falha na inserção para `{tabela_nome.upper()}`")
                    erros_totais += 1
                
            except json.JSONDecodeError as e:
                print(f"Erro ao fazer parse do JSON para `{tabela_nome.upper()}`: {e}")
                print(f"Resposta limpa: {resposta_limpa[:200]}...")
                erros_totais += 1
                continue
                
            except ValueError as e:
                print(f"Erro nos dados para `{tabela_nome.upper()}`: {e}")
                erros_totais += 1
                continue
                
        except (mysql.connector.Error, ValueError, KeyError, TypeError) as e:
            print(f"Erro crítico ao processar `{tabela_nome.upper()}`: {e}")
            erros_totais += 1
            continue
    
    # Relatório final
    print(f"\n{'='*70}")
    print("RELATÓRIO FINAL DA POPULAÇÃO DE TABELAS")
    print(f"{'='*70}")
    print(f"Tabelas processadas com sucesso: {sucessos_totais}")
    print(f"Tabelas com erro: {erros_totais}")
    print(f"Total de tabelas processadas: {tabelas_processadas}")
    print(f"Taxa de sucesso: {(sucessos_totais/(sucessos_totais+erros_totais)*100):.1f}%" if (sucessos_totais+erros_totais) > 0 else "N/A")
    print(f"{'='*70}")
    
    return sucessos_totais, erros_totais


def verify_dependencies(conexao, tabela_nome, schema):
    """
    Verifica se as dependências de uma tabela estão satisfeitas antes de popular.
    """
    dependencias = {
        'hierarquia': ['taxon'],
        'especie': ['taxon'],
        'especime': ['especie'],
        'amostra': ['especie', 'local_de_coleta'],
        'midia': ['especime'],
        'artigo': ['projeto'],
        'proj_func': ['projeto', 'funcionario'],
        'proj_esp': ['projeto', 'especie'],
        'proj_cat': ['projeto', 'categoria'],
        'contrato': ['funcionario', 'laboratorio'],
        'financiamento': ['projeto', 'financiador'],
        'registro_de_uso': ['funcionario', 'equipamento']
    }
    
    if tabela_nome not in dependencias:
        return True  # Tabela sem dependências
    
    cursor = conexao.cursor()
    try:
        for tabela_dependencia in dependencias[tabela_nome]:
            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_dependencia}`")
            count = cursor.fetchone()[0]
            if count == 0:
                print(f"Dependência não atendida: tabela `{tabela_dependencia.upper()}` está vazia")
                return False
        return True
    except mysql.connector.Error as e:
        print(f"Erro ao verificar dependências: {e}")
        return False
    finally:
        cursor.close()


def adjust_row(conexao, tabela_nome, n_linhas_original):
    """
    Ajusta o número de linhas baseado nas dependências disponíveis.
    Versão melhorada que considera múltiplas dependências.
    """
    # Mapeamento de dependências múltiplas
    dependencias_multiplas = {
        'especime': ['especie'],
        'amostra': ['especie', 'local_de_coleta'], 
        'midia': ['especime'],
        'artigo': ['projeto'],
        'proj_func': ['projeto', 'funcionario'],
        'proj_esp': ['projeto', 'especie'],
        'proj_cat': ['projeto', 'categoria'],
        'contrato': ['funcionario', 'laboratorio'],
        'financiamento': ['projeto', 'financiador'],
        'registro_de_uso': ['funcionario', 'equipamento']
    }
    
    if tabela_nome not in dependencias_multiplas:
        return n_linhas_original
    
    cursor = conexao.cursor()
    try:
        dependencias = dependencias_multiplas[tabela_nome]
        min_registros = []
        
        # Verifica o número de registros em cada tabela dependente
        for tabela_dep in dependencias:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM `{tabela_dep}`")
                count = cursor.fetchone()[0]
                min_registros.append(count)
                print(f"Tabela `{tabela_dep.upper()}` tem {count} registros disponíveis")
            except mysql.connector.Error as e:
                # Se a tabela não existe, assume 0
                print(f"Erro ao acessar tabela {tabela_dep}: {e}")
                min_registros.append(0)
        
        if not min_registros or min(min_registros) == 0:
            print(f"Nenhum registro disponível nas dependências de {tabela_nome.upper()}")
            return 0
        
        # Para tabelas de relacionamento (muitos-para-muitos), permite mais combinações
        if tabela_nome.startswith('proj_'):
            # Permite até o produto das tabelas relacionadas, mas com limite razoável
            limite_max = min(min_registros[0] * min_registros[1], n_linhas_original * 3)
        else:
            # Para outras tabelas, limita baseado na menor dependência
            limite_max = min(min_registros) * 2  # Permite até 2x o menor número
        
        limite = min(n_linhas_original, max(1, limite_max))
        
        if limite != n_linhas_original:
            print(f"Ajustando número de linhas de {n_linhas_original} para {limite} (baseado em dependências)")
        
        return limite
        
    except mysql.connector.Error as e:
        print(f"Erro ao ajustar número de linhas para {tabela_nome}: {e}")
        return n_linhas_original
    finally:
        cursor.close()


def validate_structure(registros, schema_colunas):
    """
    Valida se os registros têm a estrutura esperada baseada no schema.
    """
    if not registros or not isinstance(registros, list):
        return False
    
    if not schema_colunas:
        return True  # Se não temos schema, aceita qualquer estrutura
    
    # Pega os nomes das colunas esperadas
    colunas_esperadas = {col['nome'] for col in schema_colunas}
    
    # Verifica o primeiro registro como amostra
    primeiro_registro = registros[0]
    if not isinstance(primeiro_registro, dict):
        return False
    
    colunas_recebidas = set(primeiro_registro.keys())
    
    # Verifica se pelo menos 50% das colunas esperadas estão presentes
    intersecao = colunas_esperadas.intersection(colunas_recebidas)
    cobertura = len(intersecao) / len(colunas_esperadas) if colunas_esperadas else 1
    
    return cobertura >= 0.5


def get_available_foreign_keys(conexao, tabela_nome):
    """
    Obtém os valores disponíveis de chaves estrangeiras para uma tabela específica.
    """
    fk_mappings = {
        'hierarquia': {
            'ID_Tax': 'SELECT ID_Tax, Tipo, Nome FROM Taxon ORDER BY ID_Tax',
            'ID_TaxTopo': 'SELECT ID_Tax, Tipo, Nome FROM Taxon ORDER BY ID_Tax'
        },
        'especie': {
            'ID_Gen': 'SELECT ID_Tax, Nome FROM Taxon WHERE Tipo = "Gênero" ORDER BY ID_Tax'
        },
        'especime': {
            'ID_Esp': 'SELECT ID_Esp, Nome FROM Especie ORDER BY ID_Esp'
        },
        'amostra': {
            'ID_Esp': 'SELECT ID_Esp, Nome FROM Especie ORDER BY ID_Esp',
            'ID_Local': 'SELECT ID_Local, Nome FROM Local_de_Coleta ORDER BY ID_Local'
        },
        'midia': {
            'ID_Especime': 'SELECT ID_Especime, Descritivo FROM Especime ORDER BY ID_Especime'
        },
        'artigo': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj'
        },
        'proj_func': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj',
            'ID_Func': 'SELECT ID_Func, Nome FROM Funcionario ORDER BY ID_Func'
        },
        'proj_esp': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj',
            'ID_Esp': 'SELECT ID_Esp, Nome FROM Especie ORDER BY ID_Esp'
        },
        'proj_cat': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj',
            'ID_Categ': 'SELECT ID_Categ, Descritivo FROM Categoria ORDER BY ID_Categ'
        },
        'contrato': {
            'ID_Func': 'SELECT ID_Func, Nome FROM Funcionario ORDER BY ID_Func',
            'ID_Lab': 'SELECT ID_Lab, Nome FROM Laboratorio ORDER BY ID_Lab'
        },
        'financiamento': {
            'ID_Proj': 'SELECT ID_Proj, Nome FROM Projeto ORDER BY ID_Proj',
            'ID_Financiador': 'SELECT ID_Financiador, Descritivo FROM Financiador ORDER BY ID_Financiador'
        },
        'registro_de_uso': {
            'ID_Func': 'SELECT ID_Func, Nome FROM Funcionario ORDER BY ID_Func',
            'ID_Equip': 'SELECT ID_Equip, Tipo, Modelo FROM Equipamento ORDER BY ID_Equip'
        }
    }
    
    if tabela_nome not in fk_mappings:
        return {}
    
    cursor = conexao.cursor()
    foreign_keys_data = {}
    
    try:
        for campo, query in fk_mappings[tabela_nome].items():
            cursor.execute(query)
            resultados = cursor.fetchall()
            foreign_keys_data[campo] = resultados
            
        return foreign_keys_data
        
    except mysql.connector.Error as e:
        print(f"Erro ao obter FKs para {tabela_nome}: {e}")
        return {}
    finally:
        cursor.close()


def get_existing_data_for_context(conexao, tabelas_ja_populadas, limite_por_tabela=5):
    """
    Obtém dados das tabelas já populadas para usar como contexto na geração de novos dados.
    """
    contexto_dados = {}
    cursor = conexao.cursor()
    
    for tabela in tabelas_ja_populadas:
        try:
            # Busca alguns registros de exemplo de cada tabela
            cursor.execute(f"SELECT * FROM `{tabela}` LIMIT {limite_por_tabela}")
            registros = cursor.fetchall()
            
            if registros:
                # Obtém os nomes das colunas
                cursor.execute(f"DESCRIBE `{tabela}`")
                colunas = [col[0] for col in cursor.fetchall()]
                
                # Converte para formato legível
                registros_dict = []
                for registro in registros:
                    registro_dict = {}
                    for i, valor in enumerate(registro):
                        # Trata campos BLOB (converte para texto indicativo)
                        if isinstance(valor, bytes):
                            registro_dict[colunas[i]] = f"<BLOB:{len(valor)}bytes>"
                        else:
                            registro_dict[colunas[i]] = valor
                    registros_dict.append(registro_dict)
                
                contexto_dados[tabela] = registros_dict
                
        except mysql.connector.Error as e:
            print(f"Erro ao obter dados de {tabela}: {e}")
            continue
    
    cursor.close()
    return contexto_dados


def analyze_table_relationships(conexao, tabela_nome, tabelas_ja_populadas):
    """
    Analisa as relações entre a tabela atual e as já populadas para fornecer contexto mais rico.
    """
    relacionamentos = {}
    cursor = conexao.cursor()
    
    try:
        # Mapeamento das relações conhecidas
        relacoes_conhecidas = {
            'hierarquia': {
                'tabela_pai': 'taxon',
                'descricao': 'hierarquia taxonômica',
                'campos_relevantes': ['ID_Tax', 'ID_TaxTopo']
            },
            'especie': {
                'tabela_pai': 'taxon',
                'descricao': 'espécies por gênero',
                'campos_relevantes': ['ID_Gen']
            },
            'especime': {
                'tabela_pai': 'especie',
                'descricao': 'espécimes por espécie',
                'campos_relevantes': ['ID_Esp']
            },
            'amostra': {
                'tabelas_pai': ['especie', 'local_de_coleta'],
                'descricao': 'amostras por espécie e local',
                'campos_relevantes': ['ID_Esp', 'ID_Local']
            },
            'midia': {
                'tabela_pai': 'especime',
                'descricao': 'mídia por espécime',
                'campos_relevantes': ['ID_Especime']
            },
            'proj_func': {
                'tabelas_pai': ['projeto', 'funcionario'],
                'descricao': 'funcionários por projeto',
                'campos_relevantes': ['ID_Proj', 'ID_Func']
            },
            'proj_esp': {
                'tabelas_pai': ['projeto', 'especie'],
                'descricao': 'espécies por projeto',
                'campos_relevantes': ['ID_Proj', 'ID_Esp']
            },
            'proj_cat': {
                'tabelas_pai': ['projeto', 'categoria'],
                'descricao': 'categorias por projeto',
                'campos_relevantes': ['ID_Proj', 'ID_Categ']
            },
            'contrato': {
                'tabelas_pai': ['funcionario', 'laboratorio'],
                'descricao': 'contratos funcionário-laboratório',
                'campos_relevantes': ['ID_Func', 'ID_Lab']
            },
            'financiamento': {
                'tabelas_pai': ['projeto', 'financiador'],
                'descricao': 'financiamentos por projeto',
                'campos_relevantes': ['ID_Proj', 'ID_Financiador']
            },
            'registro_de_uso': {
                'tabelas_pai': ['funcionario', 'equipamento'],
                'descricao': 'uso de equipamentos',
                'campos_relevantes': ['ID_Func', 'ID_Equip']
            }
        }
        
        tabela_nome_lower = tabela_nome.lower()
        
        if tabela_nome_lower in relacoes_conhecidas:
            relacao = relacoes_conhecidas[tabela_nome_lower]
            relacionamentos['descricao'] = relacao['descricao']
            relacionamentos['campos_relevantes'] = relacao['campos_relevantes']
            
            # Verifica se as tabelas pai estão populadas
            tabelas_pai = []
            if 'tabela_pai' in relacao:
                tabelas_pai = [relacao['tabela_pai']]
            elif 'tabelas_pai' in relacao:
                tabelas_pai = relacao['tabelas_pai']
            
            relacionamentos['tabelas_disponeis'] = []
            for tabela_pai in tabelas_pai:
                if tabela_pai.lower() in [t.lower() for t in tabelas_ja_populadas]:
                    cursor.execute(f"SELECT COUNT(*) FROM `{tabela_pai}`")
                    count = cursor.fetchone()[0]
                    relacionamentos['tabelas_disponeis'].append({
                        'tabela': tabela_pai,
                        'registros': count
                    })
                    print(f"Relação identificada: {tabela_nome} → {tabela_pai} ({count} registros)")
        
        return relacionamentos
        
    except mysql.connector.Error as e:
        print(f"Erro ao analisar relacionamentos para {tabela_nome}: {e}")
        return {}
    finally:
        cursor.close()


def normalize_table_name(table_name, available_tables):
    """
    Normaliza nome de tabela para comparação case-insensitive.
    Retorna o nome correto da tabela se encontrado, None caso contrário.
    """
    if not table_name:
        return None
    
    table_name_lower = table_name.lower()
    
    for table in available_tables:
        if table.lower() == table_name_lower:
            return table
    
    return None


def validate_table_exists(conexao, table_name):
    """
    Verifica se uma tabela existe no banco de dados, ignorando case.
    """
    cursor = conexao.cursor()
    try:
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        return normalize_table_name(table_name, tables) is not None
    except mysql.connector.Error:
        return False
    finally:
        cursor.close()


def get_table_columns_case_insensitive(conexao, table_name):
    """
    Obtém as colunas de uma tabela de forma case-insensitive.
    """
    cursor = conexao.cursor()
    try:
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        
        correct_table_name = normalize_table_name(table_name, tables)
        if not correct_table_name:
            return None, None
        
        cursor.execute(f"DESCRIBE `{correct_table_name}`")
        columns = cursor.fetchall()
        return correct_table_name, columns
    except mysql.connector.Error as e:
        print(f"Erro ao obter colunas: {e}")
        return None, None
    finally:
        cursor.close()


def check_ai_dependencies():
    """
    Verifica se as dependências para funcionalidades de IA estão disponíveis.
    """
    dependencies = {
        'openai': 'OpenAI API para geração de dados',
        'PIL': 'Pillow para processamento de imagens', 
        'torch': 'PyTorch para modelos CLIP',
        'transformers': 'Transformers para CLIP',
        'sklearn': 'Scikit-learn para similaridade'
    }
    
    missing = []
    available = []
    
    for dep, desc in dependencies.items():
        try:
            __import__(dep)
            available.append(f"✓ {dep}: {desc}")
        except ImportError:
            missing.append(f"✗ {dep}: {desc}")
    
    print("\nDependências de IA:")
    for dep in available:
        print(dep)
    
    if missing:
        print("\nDependências ausentes:")
        for dep in missing:
            print(dep)
        print("\nAlgumas funcionalidades de IA podem não funcionar corretamente.")
    
    return len(missing) == 0


def safe_execute_query(conexao, query, params=None):
    """
    Executa uma query de forma segura com tratamento de erros.
    """
    cursor = conexao.cursor()
    try:
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
        result = cursor.fetchall()
        return True, result
    except mysql.connector.Error as e:
        print(f"Erro na query: {e}")
        return False, str(e)
    finally:
        cursor.close()


def truncate_string_for_field(value, max_length):
    """
    Trunca string para caber no campo do banco de dados.
    """
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    
    if len(value) > max_length:
        print(f"Valor truncado de {len(value)} para {max_length} caracteres")
        return value[:max_length]
    
    return value


def populate_taxon_table(conexao, n_especies=250):
    """
    Versão corrigida para popular a tabela Taxon respeitando o CHECK constraint.
    """
    try:
        print("Gerando taxonomia completa via IA...")
        
        prompt = f"""
        Gere uma taxonomia completa para aproximadamente {n_especies} espécies de laboratório científico.
        
        CREATE TABLE Taxon (
            ID_Tax integer PRIMARY KEY,
            Tipo varchar(10) NOT NULL,
            Nome varchar(50) NOT NULL,
            UNIQUE (Tipo, Nome),
            CHECK (Tipo IN ('Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero')));
        
        IMPORTANTE: Use EXATAMENTE estes tipos (respeitando a ausência de acentos):
        - Dominio
        - Reino  
        - Filo
        - Classe
        - Ordem
        - Familia
        - Genero
        
        Gere uma hierarquia taxonômica realista com:
        - 1 Domínio (Eukarya)
        - 2-3 Reinos (Animalia, Plantae, Fungi)
        - 5-8 Filos
        - 10-15 Classes
        - 20-30 Ordens
        - 40-60 Famílias
        - Gêneros suficientes para as espécies
        
        Retorne APENAS um JSON válido no formato:
        {{
            "registros": [
                {{"ID_Tax": 1, "Tipo": "Dominio", "Nome": "Eukarya"}},
                {{"ID_Tax": 2, "Tipo": "Reino", "Nome": "Animalia"}},
                {{"ID_Tax": 3, "Tipo": "Reino", "Nome": "Plantae"}}
            ]
        }}
        """
        
        resposta = generate_data(prompt, modelo="gpt-4o-mini", temperatura=0.3)
        
        if not resposta:
            print("Erro: IA não retornou dados")
            return False
        
        # Limpa a resposta antes do parse
        resposta_limpa = clean_json_response(resposta)
        
        try:
            # Parse do JSON
            dados_json = json.loads(resposta_limpa)
            
            if not isinstance(dados_json, dict) or "registros" not in dados_json:
                print("Erro: estrutura JSON inválida")
                return False
            
            registros = dados_json["registros"]
            if not registros:
                print("Erro: nenhum registro encontrado")
                return False
            
            # Valida e insere os dados
            cursor = conexao.cursor()
            tipos_validos = {'Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero'}
            registros_validos = []
            
            for item in registros:
                if isinstance(item, dict) and all(k in item for k in ['Tipo', 'Nome', 'ID_Tax']):
                    if item['Tipo'] in tipos_validos:
                        nome_truncado = str(item['Nome'])[:50]  # Trunca se necessário
                        registros_validos.append((
                            item['ID_Tax'],
                            item['Tipo'],
                            nome_truncado
                        ))
            
            if not registros_validos:
                print("Erro: nenhum registro válido encontrado")
                return False
            
            # Insere os dados
            query = "INSERT INTO Taxon (ID_Tax, Tipo, Nome) VALUES (%s, %s, %s)"
            cursor.executemany(query, registros_validos)
            conexao.commit()
            cursor.close()
            
            print(f"Taxonomia inserida: {len(registros_validos)} registros")
            return True
            
        except json.JSONDecodeError as e:
            print(f"Erro ao fazer parse do JSON: {e}")
            print(f"Resposta recebida: {resposta_limpa[:200]}...")
            return False
        
    except (mysql.connector.Error, ValueError, KeyError) as e:
        print(f"Erro crítico ao popular Taxon: {e}")
        return False  


def populate_midia_table(conexao, delay_entre_requisicoes=1):
    """
    Versão corrigida para popular a tabela Midia com imagens reais das espécies.
    Busca imagens relacionadas ao nome científico da espécie.
    """
    cursor = conexao.cursor()
    
    try:
        # Verifica dependências
        cursor.execute("SELECT COUNT(*) FROM Especime")
        count_especime = cursor.fetchone()[0]
        
        if count_especime == 0:
            print("Nenhum espécime encontrado. Tabela Especime deve ser populada primeiro.")
            return False
        
        print(f"Processando {count_especime} espécimes para mídia...")
        
        # Busca espécimes com suas espécies - inclui mais informações
        cursor.execute("""
            SELECT e.ID_Especime, s.Nome, s.Nome_Pop, s.Descricao, s.ID_Esp 
            FROM Especime e 
            JOIN Especie s ON e.ID_Esp = s.ID_Esp 
            LIMIT 15
        """)
        especimes = cursor.fetchall()
        
        if not especimes:
            print("Erro ao buscar espécimes com espécies")
            return False
        
        sucessos = 0
        falhas = 0
        
        for idx, (id_especime, nome_especie, nome_popular, descricao, id_esp) in enumerate(especimes, 1):
            print(f"  [{idx}/{len(especimes)}] Processando: {nome_especie}")
            
            # Tenta diferentes termos de busca para melhorar a qualidade das imagens
            termos_busca = [
                nome_especie,  # Nome científico
                nome_popular if nome_popular else nome_especie,  # Nome popular se disponível
                f"{nome_especie} animal" if "animal" in (descricao or "").lower() else nome_especie,
                f"{nome_especie} plant" if "plant" in (descricao or "").lower() else nome_especie,
                f"{nome_especie} specimen"  # Termo científico
            ]
            
            imagem_bytes = None
            termo_usado = None
            
            # Tenta buscar imagem com diferentes termos
            for termo in termos_busca[:2]:  # Limita a 2 tentativas para não demorar muito
                print(f"    Buscando imagem para: '{termo}'")
                imagem_bytes = search_image_web_improved(termo, timeout=8)
                if imagem_bytes:
                    termo_usado = termo
                    break
                time.sleep(0.5)  # Pausa pequena entre tentativas
            
            # Se não encontrou, cria placeholder mais informativo
            if not imagem_bytes:
                print(f"    Criando placeholder para: {nome_especie}")
                imagem_bytes = create_placeholder_image_improved(nome_especie, nome_popular, descricao)
                termo_usado = "placeholder"
            
            if imagem_bytes:
                try:
                    # Tipo mais descritivo baseado no que foi encontrado
                    if termo_usado == "placeholder":
                        tipo_midia = f"Placeholder - {nome_especie}"
                    else:
                        tipo_midia = f"Foto científica - {nome_especie}"
                    
                    cursor.execute(
                        "INSERT INTO Midia (ID_Especime, Tipo, Dado) VALUES (%s, %s, %s)",
                        (id_especime, tipo_midia[:50], imagem_bytes)  # Limita o tamanho do campo Tipo
                    )
                    sucessos += 1
                    print(f"    ✅ Mídia inserida com sucesso ({termo_usado})")
                except mysql.connector.Error as e:
                    print(f"    ❌ Erro DB: {e}")
                    falhas += 1
            else:
                falhas += 1
                print(f"    ❌ Falha total ao obter imagem para {nome_especie}")
            
            # Delay entre requisições para não sobrecarregar APIs
            if idx < len(especimes):
                time.sleep(delay_entre_requisicoes)
        
        conexao.commit()
        print(f"\n📊 Resultado da população de mídia:")
        print(f"✅ Sucessos: {sucessos}")
        print(f"❌ Falhas: {falhas}")
        print(f"📈 Taxa de sucesso: {(sucessos/(sucessos+falhas)*100):.1f}%" if (sucessos+falhas) > 0 else "N/A")
        
        return sucessos > 0
        
    except mysql.connector.Error as e:
        print(f"Erro ao popular Midia: {e}")
        return False
    finally:
        cursor.close()


def truncate_value(value, max_length):
    if isinstance(value, str) and len(value) > max_length:
        return value[:max_length]
    return value


def format_check(resultado, campo=None):
    '''Formata e exibe os valores permitidos de uma CHECK constraint.
    Parâmetros:
        resultado: Resultado da consulta de CHECK constraints.
        campo: (opcional) Nome do campo específico para filtrar os resultados.
    Retorna:
        None.
    '''
    check = (resultado[1] if isinstance(resultado, tuple) else resultado).replace("\\'", "'")
    match = re.search(r"`(\w+)`\s+in\s*\((.*?)\)", check, re.IGNORECASE)
    
    if match:
        if campo and campo.lower() != match.group(1).lower():
            return
        
        atributo = match.group(1)
        valores = match.group(2)
        
        valores_formatados = re.findall(r"'([^']+)'", valores)
        print(f"\nValores permitidos para '{atributo}': {', '.join(valores_formatados)}")


def check_check(conexao, tabela, campo=None):
    '''
    Verifica se a tabela possui CHECK constraints
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
        tabela: Nome da tabela a ser verificada.
        campo: (opcional) Nome do campo específico para filtrar os resultados.
    Retorna:
        None.
    '''
    cursor = conexao.cursor()
    cursor.execute("SET NAMES utf8mb4;")
    
    cursor.execute(f"SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE FROM information_schema.check_constraints cc JOIN information_schema.table_constraints tc ON cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME WHERE tc.TABLE_NAME = '{tabela}' AND tc.TABLE_SCHEMA = 'trabalho_final' AND tc.CONSTRAINT_TYPE = 'CHECK';")
    resultados = cursor.fetchall()
    
    if campo:
        for resultado in resultados:
            format_check(resultado, campo)
    else:
        for resultado in resultados:
            format_check(resultado)
                
    cursor.close()


def check_type(campo, tipo_campo):
    """
    Verifica se o valor de entrada é compatível com o tipo do campo.
    Parâmetros:
        tipo_campo (str): Tipo do campo.
    Retorna:
        valor (int, float, str, None): Valor convertido para o tipo correto ou None se inválido.
    """
    if 'timestamp' in tipo_campo:
        valor = (datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        print(f"• {campo} ({tipo_campo}): {valor} [AUTO-GERADO]")
    elif 'blob' in tipo_campo:
        valor_input = input(f"• {campo} ({tipo_campo}). Digite o caminho do arquivo: ").strip()
        if valor_input.lower() == 'null' or valor_input == '':
            valor = None
        else:
            try:
                with open(valor_input, 'rb') as f:
                    valor = f.read()
            except FileNotFoundError:
                print(f"Arquivo '{valor_input}' não encontrado. Usando valor None.")
                valor = None
    else:
        valor_input = input(f"• {campo} ({tipo_campo}): ").strip()
        
        # CORRIGINDO: processamento do valor baseado no tipo
        if valor_input.lower() == 'null' or valor_input == '':
            valor = None
        elif 'int' in tipo_campo:
            try:
                valor = int(valor_input)
            except ValueError:
                print(f"Valor inválido para {campo}. Usando 0.")
                valor = 0
        elif 'decimal' in tipo_campo or 'float' in tipo_campo:
            try:
                valor = float(valor_input)
            except ValueError:
                print(f"Valor inválido para {campo}. Usando 0.0.")
                valor = 0.0
        elif 'date' in tipo_campo:
            # Verifica se a data está no formato YYYY-MM-DD
            if re.match(r'^\d{4}-\d{2}-\d{2}$', valor_input):
                valor = valor_input
            else:
                print(f"Formato de data inválido para {campo}. Usando data atual.")
                valor = (datetime.now()).strftime('%Y-%m-%d')
        elif 'varchar' in tipo_campo:
            # Extrai o tamanho máximo do varchar
            match = re.search(r'varchar\((\d+)\)', tipo_campo)
            if match:
                max_len = int(match.group(1))
                if len(valor_input) > max_len:
                    print(f"Valor para {campo} excede o tamanho máximo de {max_len} caracteres. Truncando.")
                    valor = valor_input[:max_len]
                else:
                    valor = valor_input
            else:
                valor = valor_input
        else:
            valor = valor_input
    
    return valor


def insert_by_user(conexao):
    """
    Solicita ao usuário o nome da tabela, os campos e valores a serem inseridos, e realiza a operação.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    """
    print("\n" + "="*50)
    print("\nTabelas Disponíveis:")
    cursor = conexao.cursor()

    # Exibe tabelas disponíveis
    tabelas = print_tables(conexao)

    # Solicita nome da tabela
    tabela_nome = input("\nDigite o nome da tabela para inserir dados: ").strip().lower()
    
    if tabela_nome not in tabelas:
        print(f"Tabela `{tabela_nome.upper()}` não encontrada.")
        cursor.close()
        return

    # Exibe colunas da tabela selecionada
    cursor.execute(f"DESCRIBE `{tabela_nome}`")
    colunas_detalhadas = cursor.fetchall()
    colunas = [col[0] for col in colunas_detalhadas]
    
    print(f"\nTabela selecionada: {tabela_nome.upper()}")
    print("Colunas disponíveis:")
    for i, col_info in enumerate(colunas_detalhadas, 1):
        nome_col = col_info[0]
        tipo_col = col_info[1]
        null_col = col_info[2]
        key_col = col_info[3]
        
        # Indica se é obrigatório
        obrigatorio = "OBRIGATÓRIO" if null_col == 'NO' and key_col != 'PRI' else ""
        auto_increment = "AUTO_INCREMENT" if 'auto_increment' in str(col_info).lower() else ""
        
        status = []
        if key_col == 'PRI':
            status.append("PK")
        if auto_increment:
            status.append("AI")
        if obrigatorio:
            status.append("OBRIGATÓRIO")
        
        status_str = f" [{', '.join(status)}]" if status else ""
        print(f"\t• {nome_col}: {tipo_col}{status_str}")
    
    check_check(conexao, tabela_nome)
    
    # Exibe valores já registrados na tabela
    print("\nValores registrados:")
    show_table(conexao, tabela_nome)

    # Coleta valores para cada campo
    print("\nPreencha os valores para cada campo (digite 'null' para deixar campo vazio):")
    valores = []
    for campo in colunas:
        # Busca informações do campo
        campo_info = next((col for col in colunas_detalhadas if col[0] == campo), None)
        tipo_campo = (campo_info[1] if campo_info else "unknown").lower()
        
        # Solicita valor do usuário
        valor = check_type(campo, tipo_campo)
        
        # Insere o valor na lista
        valores.append(valor)

    # Confirma inserção
    print("\n" + "="*50)
    print("\nResumo da inserção:")
    print(f"Tabela: {tabela_nome.upper()}")
    for campo, valor in zip(colunas, valores):
        print(f"\t• {campo}: {valor}")

    confirmacao = input("\nConfirmar inserção? (s/N): ").strip().lower()
    if confirmacao not in ['s', 'sim', 'y', 'yes']:
        print("Inserção cancelada.")
        cursor.close()
        return

    # Insere os dados
    try:
        insert_data(conexao, tabela_nome, colunas, [tuple(valores)])
    except (mysql.connector.Error, ValueError) as e:
        print(f"Inserção falhou: {e}")
    finally:
        cursor.close()
    print("\n" + "="*50)


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
    cursor = conexao.cursor()

    print("\n" + "="*50)
    print("\nTabelas Disponíveis:")
    print_tables(conexao)
    
    tabela_nome = input("\nSelecione a Tabela: ").strip().lower()
    
    print("\nValores registrados:")
    num_linhas = show_table(conexao, tabela_nome)
    
    if num_linhas == 0:
        cursor.close()
        return

    campo = input("\nCampo a atualizar: ").strip()
    
    print("\n")
    check_check(conexao, tabela_nome, campo)
    
    cursor.execute(f"DESCRIBE `{tabela_nome}`")
    colunas_detalhadas = cursor.fetchall()
    campo_info = next((col for col in colunas_detalhadas if col[0] == campo), None)
    tipo_campo = (campo_info[1] if campo_info else "unknown").lower()
    cursor.close()
    
    print("\nNovo valor:")
    valor = check_type(campo, tipo_campo)
    condicao = input("\nInsira a condição WHERE (ex: id =  1): ").strip()

    query = f"UPDATE `{tabela_nome}` SET `{campo}` = %s WHERE {condicao}"
    try:
        cursor = conexao.cursor()
        cursor.execute(query, (valor,))
        conexao.commit()
        cursor.close()
        print("Atualização feita com sucesso.")
    except mysql.connector.Error as err:
        print(f"Erro: {err}")
    print("\n" + "="*50)


def delete_by_user(conexao):
    """
    Deleta linhas de uma tabela do banco de dados com base em uma condição fornecida pelo usuário.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    """
    print("\n" + "="*50)
    print_tables(conexao)
    
    tabela_nome = input("\nSelecione a Tabela: ").strip().lower()
    
    print("\nValores registrados:")
    show_table(conexao, tabela_nome)
    
    condicao = input("\nInsira a condição WHERE (ex: id = 1): ").strip()

    query = f"DELETE FROM `{tabela_nome}` WHERE {condicao}"
    try:
        cursor = conexao.cursor()
        cursor.execute(query)
        conexao.commit()
        cursor.close()
        print("\nLinhas deletadas com sucesso.")
    except mysql.connector.Error as err:
        print(f"Erro: {err}")
    print("\n" + "="*50)


def generate_sql_query(user_prompt, schema, modelo="gpt-4o-mini", temperatura=0.3):
    """
    Gera uma query SQL baseada em um pedido do usuário respeitando rigorosamente o schema do banco.
    Versão melhorada com validação mais rigorosa do schema.
    """
    if not schema:
        print("Schema não fornecido para geração de SQL")
        return None
    
    # Identifica tabelas mencionadas no prompt
    texto = user_prompt.lower()
    tabelas_relevantes = []

    # Palavras-chave melhoradas baseadas no schema real
    palavras_chave_tabela = {
        'especie': ['Especie', 'Especime'],
        'especies': ['Especie', 'Especime'],  
        'taxonomia': ['Taxon', 'Hierarquia', 'Especie'],
        'taxonomico': ['Taxon', 'Hierarquia'],
        'classificacao': ['Taxon', 'Hierarquia'],
        'projeto': ['Projeto', 'Artigo', 'Proj_Func', 'Proj_Esp', 'Proj_Cat'],
        'projetos': ['Projeto', 'Artigo', 'Proj_Func', 'Proj_Esp', 'Proj_Cat'],
        'funcionario': ['Funcionario', 'Contrato', 'Proj_Func'],
        'funcionarios': ['Funcionario', 'Contrato', 'Proj_Func'],
        'empregado': ['Funcionario'],
        'trabalhador': ['Funcionario'],
        'laboratorio': ['Laboratorio', 'Equipamento', 'Contrato'],
        'laboratorios': ['Laboratorio', 'Equipamento', 'Contrato'],
        'lab': ['Laboratorio'],
        'midia': ['Midia'],
        'imagem': ['Midia'],
        'imagens': ['Midia'],
        'foto': ['Midia'],
        'amostra': ['Amostra', 'Local_de_Coleta'],
        'amostras': ['Amostra', 'Local_de_Coleta'],
        'coleta': ['Amostra', 'Local_de_Coleta'],
        'local': ['Local_de_Coleta'],
        'financiamento': ['Financiamento', 'Financiador'],
        'financiador': ['Financiador'],
        'verba': ['Financiamento'],
        'equipamento': ['Equipamento'],
        'equipamentos': ['Equipamento'],
        'artigo': ['Artigo'],
        'artigos': ['Artigo'],
        'publicacao': ['Artigo'],
        'contrato': ['Contrato'],
        'contratos': ['Contrato']
    }

    # Busca por palavras-chave
    for palavra, tabelas in palavras_chave_tabela.items():
        if palavra in texto:
            tabelas_relevantes.extend(tabelas)

    # Busca por nomes exatos de tabelas (case-insensitive)
    for tabela_nome in schema.keys():
        if tabela_nome.lower() in texto:
            tabelas_relevantes.append(tabela_nome)

    # Remove duplicatas
    tabelas_relevantes = list(set(tabelas_relevantes))
    
    # Se não encontrou tabelas específicas, usa heurística baseada no tipo de query
    if not tabelas_relevantes:
        if any(palavra in texto for palavra in ['todos', 'todas', 'listar', 'mostrar', 'contar']):
            # Para queries gerais, inclui tabelas principais
            tabelas_relevantes = ['Especie', 'Taxon', 'Projeto', 'Funcionario']
        else:
            # Usa todas as tabelas como fallback
            tabelas_relevantes = list(schema.keys())[:5]  # Limita para evitar queries muito complexas

    # Inclui tabelas relacionadas baseado no schema real
    tabelas_com_relacionamentos = set(tabelas_relevantes)
    
    # Mapeamento de relacionamentos baseado no schema SQL real
    relacionamentos_schema = {
        'Especime': ['Especie'],
        'Especie': ['Taxon'],
        'Hierarquia': ['Taxon'],
        'Midia': ['Especime', 'Especie'],
        'Amostra': ['Especie', 'Local_de_Coleta'],
        'Artigo': ['Projeto'],
        'Proj_Func': ['Projeto', 'Funcionario'],
        'Proj_Esp': ['Projeto', 'Especie'],
        'Proj_Cat': ['Projeto', 'Categoria'],
        'Contrato': ['Funcionario', 'Laboratorio'],
        'Financiamento': ['Projeto', 'Financiador'],
        'Registro_de_Uso': ['Funcionario', 'Equipamento']
    }
    
    for tabela in list(tabelas_relevantes):
        if tabela in relacionamentos_schema:
            tabelas_com_relacionamentos.update(relacionamentos_schema[tabela])

    # Filtra apenas tabelas que existem no schema
    schema_reduzido = {t: schema[t] for t in tabelas_com_relacionamentos if t in schema}

    # Monta informação detalhada do schema
    schema_detalhado = []
    for tabela, colunas in schema_reduzido.items():
        colunas_info = []
        for col in colunas:
            col_info = f"{col['nome']} ({col['tipo']})"
            # Adiciona informações sobre restrições se disponíveis
            if 'NOT NULL' in col.get('extra', '').upper():
                col_info += " NOT NULL"
            if 'PRIMARY KEY' in col.get('extra', '').upper():
                col_info += " PK"
            colunas_info.append(col_info)
        
        schema_detalhado.append(f"{tabela}: {', '.join(colunas_info)}")

    # Informação específica dos relacionamentos baseada no schema SQL
    relacionamentos_info = """
    RELACIONAMENTOS E CHAVES ESTRANGEIRAS (CRÍTICO):
    - Especie.ID_Gen → Taxon.ID_Tax (gênero da espécie)
    - Especime.ID_Esp → Especie.ID_Esp (espécie do espécime)
    - Midia.ID_Especime → Especime.ID_Especime (mídia do espécime)
    - Amostra.ID_Esp → Especie.ID_Esp (espécie da amostra)
    - Amostra.ID_Local → Local_de_Coleta.ID_Local (local da amostra)
    - Hierarquia.ID_Tax → Taxon.ID_Tax (taxa filho)
    - Hierarquia.ID_TaxTopo → Taxon.ID_Tax (taxa pai)
    - Artigo.ID_Proj → Projeto.ID_Proj (projeto do artigo)
    - Contrato.ID_Func → Funcionario.ID_Func (funcionário do contrato)
    - Contrato.ID_Lab → Laboratorio.ID_Lab (laboratório do contrato)
    - Proj_Func.ID_Proj → Projeto.ID_Proj e Proj_Func.ID_Func → Funcionario.ID_Func
    - Proj_Esp.ID_Proj → Projeto.ID_Proj e Proj_Esp.ID_Esp → Especie.ID_Esp
    - Financiamento.ID_Proj → Projeto.ID_Proj e ID_Financiador → Financiador.ID_Financiador
    
    CONSTRAINTS IMPORTANTES:
    - Taxon.Tipo IN ('Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero')
    - Especie.IUCN IN ('LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX')
    - Projeto.Status IN ('Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado')
    - Contrato.Status IN ('Pendente', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado')
    """
    
    prompt = f"""
    Você é um especialista em SQL para bancos de dados de taxonomia e laboratórios científicos.
    
    CONTEXTO DO BANCO DE DADOS:
    Este é um sistema para laboratórios de pesquisa em taxonomia que gerencia:
    - Taxonomia de espécies (Dominio → Reino → Filo → Classe → Ordem → Familia → Genero → Especie)
    - Espécimes coletados e suas mídias (fotos, vídeos)
    - Projetos de pesquisa e seus funcionários
    - Laboratórios, equipamentos e contratos
    - Amostras biológicas e locais de coleta
    - Financiamentos e artigos científicos
    
    SCHEMA EXATO DO BANCO (USE APENAS ESTES CAMPOS):
    {chr(10).join(schema_detalhado)}
    
    {relacionamentos_info}
    
    PEDIDO DO USUÁRIO: "{user_prompt}"
    
    INSTRUÇÕES CRÍTICAS:
    1. Use APENAS nomes de tabelas e colunas EXATOS do schema acima
    2. Para buscar por nomes específicos (ex: "Laboratório de Estudo de Insetos"), use LIKE '%palavra%'
    3. Se não souber um nome exato, use LIKE com palavras-chave relevantes
    4. Para funcionários em laboratórios: JOIN Funcionario → Contrato → Laboratorio
    5. Para espécies em projetos: JOIN Projeto → Proj_Esp → Especie
    6. Use JOINs corretos baseados nas FKs listadas
    7. Para campos de Status/Tipo, use APENAS valores das constraints
    8. Datas no formato 'YYYY-MM-DD', aspas simples para strings
    9. NUNCA invente nomes de laboratórios/projetos - use LIKE para buscar
    10. Se precisar de LIMIT, use um valor razoável (10-20)
    
    EXEMPLOS DE QUERIES CORRETAS:
    - SELECT f.Nome FROM Funcionario f JOIN Contrato c ON f.ID_Func = c.ID_Func JOIN Laboratorio l ON c.ID_Lab = l.ID_Lab WHERE l.Nome LIKE '%Insetos%'
    - SELECT e.Nome, t.Nome FROM Especie e JOIN Taxon t ON e.ID_Gen = t.ID_Tax WHERE t.Tipo = 'Genero' LIMIT 10
    - SELECT p.Nome, COUNT(f.ID_Func) FROM Projeto p JOIN Proj_Func pf ON p.ID_Proj = pf.ID_Proj JOIN Funcionario f ON pf.ID_Func = f.ID_Func GROUP BY p.Nome
    
    DICAS PARA O PEDIDO ATUAL:
    - Se procura funcionários em laboratório específico: use JOIN com Contrato e Laboratorio
    - Se procura espécies: use tabelas Especie e Taxon
    - Se procura projetos: use tabela Projeto e suas relações
    - Use LIKE '%palavra%' quando não souber o nome exato
    
    INSTRUÇÕES DE RESPOSTA:
    - Retorne APENAS a query SQL completa
    - UMA ÚNICA LINHA, sem quebras
    - SEM comentários ou explicações
    - SEM blocos de código markdown
    - Query deve ser executável imediatamente
    
    SQL:
    """
    
    # Gera a resposta
    resposta = generate_data(prompt, modelo=modelo, temperatura=temperatura)
    
    if resposta:
        # Limpeza mais rigorosa da resposta
        resposta_limpa = resposta.strip()
        
        # Remove markdown
        resposta_limpa = re.sub(r'```sql\s*', '', resposta_limpa, flags=re.IGNORECASE)
        resposta_limpa = re.sub(r'```\s*', '', resposta_limpa)
        
        # Remove prefixos comuns
        resposta_limpa = re.sub(r'^(SQL:|Query:|Resposta:|SELECT\s*SQL:)\s*', '', resposta_limpa, flags=re.IGNORECASE)
        
        # Remove quebras de linha e normaliza espaços
        resposta_limpa = re.sub(r'\n+', ' ', resposta_limpa)
        resposta_limpa = re.sub(r'\s+', ' ', resposta_limpa)
        resposta_limpa = resposta_limpa.strip()
        
        # Validação básica da query
        if resposta_limpa:
            # Verifica se contém palavras-chave SQL essenciais
            palavras_sql = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'SHOW', 'DESCRIBE']
            if any(palavra in resposta_limpa.upper() for palavra in palavras_sql):
                
                # Validação adicional: verifica se não usa tabelas/campos inexistentes
                tabelas_schema = set(schema.keys())
                palavras_query = resposta_limpa.upper().split()
                
                # Lista de palavras que não são nomes de tabelas (palavras reservadas SQL)
                palavras_reservadas = {
                    'SELECT', 'FROM', 'WHERE', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'ON', 
                    'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'AS', 'AND', 'OR', 'NOT',
                    'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT', 'ALL', 'IN', 'LIKE',
                    'BETWEEN', 'IS', 'NULL', 'ASC', 'DESC', 'UNION', 'INSERT', 'INTO',
                    'VALUES', 'UPDATE', 'SET', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'TABLE'
                }
                
                # Validação mais inteligente - remove falsos positivos
                palavras_suspeitas = []
                
                # Lista expandida de palavras que devem ser ignoradas na validação
                palavras_ignorar = {
                    'SELECT', 'FROM', 'WHERE', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'ON', 
                    'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'AS', 'AND', 'OR', 'NOT',
                    'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT', 'ALL', 'IN', 'LIKE',
                    'BETWEEN', 'IS', 'NULL', 'ASC', 'DESC', 'UNION', 'INSERT', 'INTO',
                    'VALUES', 'UPDATE', 'SET', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'TABLE',
                    # Palavras comuns em português que podem aparecer em strings
                    'DE', 'DA', 'DO', 'DAS', 'DOS', 'EM', 'NO', 'NA', 'NOS', 'NAS',
                    'COM', 'SEM', 'PARA', 'POR', 'ENTRE', 'SOBRE', 'CONTRA', 'DURANTE',
                    'LABORATORIO', 'LABORATÓRIO', 'ESTUDO', 'ESTUDOS', 'PESQUISA', 
                    'CENTRO', 'INSTITUTO', 'DEPARTAMENTO', 'SETOR', 'UNIDADE',
                    'INSETOS', 'PLANTAS', 'ANIMAIS', 'FUNGOS', 'BACTERIAS',
                    'ESPECIES', 'ESPECIME', 'GENETICA', 'BIOLOGIA', 'TAXONOMIA'
                }
                
                # Extrai todas as colunas do schema para validação
                todas_colunas = set()
                for tabela_cols in schema.values():
                    for col in tabela_cols:
                        todas_colunas.add(col['nome'].upper())
                
                for palavra in palavras_query:
                    palavra_limpa = palavra.strip('(),;`"\'').upper()
                    
                    # Só considera suspeita se:
                    # 1. É uma palavra alfabética longa (>5 chars)
                    # 2. Não está nas palavras reservadas/ignorar
                    # 3. Não é nome de tabela conhecida
                    # 4. Não é nome de coluna conhecida
                    # 5. Não parece ser uma string literal (contém espaços, pontos, etc.)
                    if (palavra_limpa.isalpha() and 
                        len(palavra_limpa) > 5 and 
                        palavra_limpa not in palavras_ignorar and
                        palavra_limpa not in [t.upper() for t in tabelas_schema] and
                        palavra_limpa not in todas_colunas and
                        not any(char in palavra.lower() for char in [' ', '.', '-', '_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'])):
                        palavras_suspeitas.append(palavra_limpa)
                
                # Só regenera se houver palavras realmente suspeitas (muito restritivo agora)
                if len(palavras_suspeitas) > 2:  # Só se tiver mais de 2 palavras suspeitas
                    print(f"Muitas palavras desconhecidas detectadas: {palavras_suspeitas[:3]}...")
                    print("Regenerando query com foco no schema...")
                    
                    # Prompt mais focado no schema real
                    prompt_restrito = f"""
                    VOCÊ DEVE USAR APENAS ESTE SCHEMA:
                    
                    TABELAS E COLUNAS EXATAS:
                    {chr(10).join(schema_detalhado)}
                    
                    PEDIDO: "{user_prompt}"
                    
                    IMPORTANTE:
                    - Use APENAS tabelas: {', '.join(schema.keys())}
                    - NÃO invente nomes de laboratórios, use apenas: SELECT * FROM Laboratorio para ver os nomes reais
                    - Para buscar por nome, use LIKE '%palavra%'
                    - NUNCA use palavras que não existem no schema acima
                    
                    Gere SQL válido usando APENAS o schema mostrado:
                    """
                    
                    resposta_2 = generate_data(prompt_restrito, modelo=modelo, temperatura=0.1)
                    
                    if resposta_2:
                        resposta_limpa_2 = re.sub(r'```sql\s*', '', resposta_2.strip(), flags=re.IGNORECASE)
                        resposta_limpa_2 = re.sub(r'```\s*', '', resposta_limpa_2)
                        resposta_limpa_2 = re.sub(r'\n+', ' ', resposta_limpa_2)
                        resposta_limpa_2 = re.sub(r'\s+', ' ', resposta_limpa_2).strip()
                        
                        if any(palavra in resposta_limpa_2.upper() for palavra in palavras_sql):
                            resposta_limpa = resposta_limpa_2
                
                return resposta_limpa.strip()
    
    print("Falha ao gerar query SQL válida")
    return None


def make_query(conexao, sql_query):
    """
    Executa uma consulta SQL na conexão fornecida e exibe os resultados.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados.
        sql_query (str): Consulta SQL a ser executada.
    """
    cursor = conexao.cursor()
    
    try:
        cursor.execute(sql_query)
        resultados = cursor.fetchall()
        colunas = [desc[0] for desc in cursor.description]

        if resultados:
            print(f"Resultados da query '{sql_query}':")
            for linha in resultados:
                print(dict(zip(colunas, linha)))
        else:
            print("Nenhum resultado encontrado.")
    except mysql.connector.Error as err:
        print(f"Erro ao executar a query: {err}")
    finally:
        cursor.close()


def generate_embeddings(img_bytes):
    """
    Gera um vetor de embedding normalizado para uma imagem fornecida em bytes.
    Parâmetros:
        img_bytes (bytes): Os bytes da imagem a ser processada.
    Retorna:
        np.ndarray ou None: O vetor de embedding normalizado da imagem, ou None em caso de erro.
    """
    
    # Verifica se CLIP está disponível
    if not CLIP_AVAILABLE:
        print("❌ CLIP não disponível para gerar embeddings")
        return None
    
    # Carrega o modelo CLIP apenas quando necessário
    if not load_clip_model():
        return None
    
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
    
    if emb_consulta is None:
        print("Erro ao gerar embedding da imagem de consulta.")
        return

    # Gere embeddings das imagens do banco
    embeddings = []
    ids = []
    for id_midia, dado in midias:
        try:
            emb = generate_embeddings(dado)
            if emb is not None:
                embeddings.append(emb)
                ids.append(id_midia)
        except (OSError, IOError) as e:
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
        # Corrigida a consulta SQL baseada no schema real
        cursor.execute("""
            SELECT e.Nome, e.Descricao
            FROM Midia m
            JOIN Especime es ON m.ID_Especime = es.ID_Especime
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

    
    if schema:
        # 5. Atualizar algumas linhas aleatórias de uma tabela
        tabela_exemplo = next(iter(schema))
        print(f"\n[CRUD] Atualizando 3 linhas aleatórias da tabela '{tabela_exemplo}'...")
        update_random_rows(conexao, tabela_nome=tabela_exemplo, n_linhas=3)

        # 6. Deletar algumas linhas aleatórias da mesma tabela
        print(f"\n[CRUD] Deletando 2 linhas aleatórias da tabela '{tabela_exemplo}'...")
        delete_random_rows(conexao, tabela_nome=tabela_exemplo, n_linhas=2)

    print("\n[CRUD] CRUD automatizado finalizado.")


def normalize_case_sensitive_name(name):
    """
    Normaliza o nome para comparações case-insensitive.
    """
    return name.lower() if name else name


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
║ [  8 ] > IA: Atualizar Dados Aleatórios     ║
║ [  9 ] > IA: Gerar SQL a partir de Texto    ║
║ [ 10 ] > IA: Buscar Imagens Similares       ║
║ [ 11 ] > Executar CRUD Automático           ║
║ [ 12 ] > Remover Dados Aleatórios           ║
║ [  0 ] > Explodir Sistema                   ║
╚═════════════════════════════════════════════╝
""")

            try:
                opcao = int(input("Opção: ").strip())
                if opcao < 0 or opcao > 12:
                    print("Opção inválida. Escolha um número entre 0 e 12.")
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
                    tabela = input("Tabela para atualizar: ").strip()
                    n = input("Quantas linhas aleatórias? [padrão=5]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 5
                    update_random_rows(con, tabela_nome=tabela, n_linhas=n)

                case 9:
                    prompt_usuario = input("Digite sua consulta em linguagem natural: ").strip()
                    if prompt_usuario:
                        db_schema = get_schema_info(con)
                        query = generate_sql_query(prompt_usuario, db_schema)
                        if query:
                            print(f"Query gerada: {query}")
                            make_query(con, query)
                        else:
                            print("Erro: não foi possível gerar a query SQL")
                
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