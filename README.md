# TrabalhoFinalBD
Este projeto, elaborado para a disciplina de Banco de Dados na UFSC, tem como objetivo o desenvolvimento de um modelo de banco de dados e uma aplicação que integre inteligência artificial.

## Autores
- Samuel Alves de Oliveira Rovida (23102572)
- Thomas Tavares Tomaz (23102571)

## Introdução
A fim de gerenciar um laboratório de taxonomia, foi desenvolvido um projeto de banco de dados com tabelas referentes aos pesquisadores, às amostras biológicas, aos espécimes vivos, aos equipamentos do laboratório, aos projetos de pesquisa e à classificação taxonômica das espécies.

Além disso, também foram criadas tabelas referentes à artigos científicos produzidos pelos pesquisadores no laboratório, bem como as relações com as espécies catalogadas. Por fim, desenvolveu-se uma aplicação que integra um modelo de IA, com os objetivos de popular o banco de dados com as espécies e facilitar a pesquisa do usuário.

## Descrição Detalhada
A fim de especificar o modelo do banco de dados, foram elaborados os seguintes requisitos para o projeto:

- O sistema deve ser capaz de armazenar a estrutura taxonômica de diferentes espécies de seres vivos. A taxonomia de uma espécie é dividida em **táxons** (unidade taxonômica nomeada) da seguinte forma (do mais geral ao mais específico): Domínio, Reino, Filo, Classe, Ordem, Família, Gênero e Espécie. Cada táxon possui um **identificador**, um **tipo** (dentre a hierarquia) e um **nome**, além de estar relacionado com apenas um táxon do nível hierárquico superior. Por fim, cada táxon pode estar relacionado com diferentes táxons do nível hierárquico inferior.
- Para a **espécie**, o nível taxonômico mais baixo, devem ser armazenadas informações como **identificador**, **nome**, **descrição** e **IUCN** (nível de conservação). O nível IUCN varia de pouco preocupante (LC) até extinto (EX). A espécie segue a mesma regra de hierarquia dos táxons.
- Para cada espécie, é necessário o registro de diferentes **espécimes**. Cada espécime deve possuir um **identificador** e um **descritivo**. Um espécime deve estar relacionado com apenas uma espécie e uma espécie pode possuir diferentes espécimes.
- Um espécime armazenado no banco de dados pode possuir um ou mais arquivos de **mídia**, como imagens e áudios. É necessário armazenar o **identificador** do arquivo de mídia, bem como seu **tipo** e uma **descrição**.
- Além de espécimes, o sistema deve permitir o registro de **amostras** de espécies. Uma amostra possui um **identificador** e um **tipo** (sangue, pele, fóssil, etc).
- Cada amostra também deve estar relacionada com um **local de coleta**, sendo armazenada a **data da coleta** da amostra. Cada local possui um **identificador**, um **nome** e um **endereço**.
- O sistema também deve proporcionar o registro de diferentes espaços de **laboratório**. Cada laboratório possui um **identificador**, um **nome** e um **endereço**, além de possuir diferentes **funcionários** e **equipamentos**.
- Funcionários se relacionam com um laboratório por meio de um **contrato**, que possui **identificador**, **status** (ativo ou concluído), **valor**, além das **datas de início** e **fim**. 
- Cada **funcionário** precisa ter um **identificador**, um **nome**, um **cargo** e seu **número de CPF** e podem, ao longo do tempo, estar relacionados com diferentes laboratórios através de diferentes contratos.
- **Equipamentos** devem possuir um **identificador**, além de um **tipo** e um **modelo** e precisam estar relacionados com apenas um laboratório.
- Funcionários específicos podem usar os equipamentos do laboratório, e portanto, o **registro de uso** desses equipamentos deve poder ser registrado, junto com a **data** do uso.
- **Projetos** de pesquisa precisam ser armazenados no sistema. Cada projeto possui um **identificador**, um **nome** e uma **descrição**. Além disso, projetos necessitam estar relacionados com funcionários pesquisadores e espécies.
- Projetos também possuem **categorias**, que são diferenciadas por um atributo **identificador** e um **descritivo**.
- **Financiadores** – que possuem os atributos: **identificador**, **descritivo** e **endereço** – podem financiar diferentes projetos de pesquisa. Para um **financiamento**, devem ser registrados: **identificador**, **valor** financiado e a **data** do financiamento.
- Por fim, projetos de pesquisa podem culminar em **artigos** científicos. Para cada artigo, o sistema deve permitir o registro de um **identificador**, seu Identificador de Objeto Digital (**DOI**), bem como **título**, **resumo** e um ***link*** para acesso do artigo. Diferentes artigos podem se originar de um projeto, e portanto, também é necessário o registro da **data de publicação** do artigo.

## MODELO CONCEITUAL

## MODELO LÓGICO

## SCRIPT DDL
```sql
CREATE TABLE Taxon (
	ID_Tax integer PRIMARY KEY,
	Tipo varchar(10),
	Nome varchar(50),
	CHECK (Tipo IN ('Domínio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Família', 'Gênero')));

CREATE TABLE Hierarquia (
	ID_Tax integer PRIMARY KEY,
	ID_TaxTopo integer,
	FOREIGN KEY(ID_Tax) REFERENCES Taxon (ID_Tax),
	FOREIGN KEY(ID_TaxTopo) REFERENCES Taxon (ID_Tax));

CREATE TABLE Especie (
	ID_Esp integer PRIMARY KEY,
	ID_Gen integer,
	Nome varchar(50),
	Descricao varchar(2500),
	IUCN varchar(2),
	FOREIGN KEY(ID_Gen) REFERENCES Taxon (ID_Tax));

CREATE TABLE Especime (
	ID_Especime integer PRIMARY KEY,
	ID_Esp integer,
	Descritivo varchar(50),
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp));

CREATE TABLE Local_de_Coleta (
	ID_Local integer PRIMARY KEY,
	Nome varchar(50),
	Endereco varchar(100));

CREATE TABLE Amostra (
	ID_Amos integer PRIMARY KEY,
	ID_Esp integer,
	ID_Local integer,
	Tipo varchar(50),
	Dt_Coleta date,
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp),
	FOREIGN KEY(ID_Local) REFERENCES Local_de_Coleta (ID_Local));

CREATE TABLE Midia (
	ID_Midia integer PRIMARY KEY,
	ID_Especime integer,
	Tipo varchar(50),
	Dado blob,	-- BLOB = Binary Large Object
	FOREIGN KEY(ID_Especime) REFERENCES Especime (ID_Especime));

CREATE TABLE Projeto (
	ID_Proj integer PRIMARY KEY,
	Nome varchar(50),
	Descricao varchar(100),
	Status varchar(50),
	Dt_Inicio date,
	Dt_Fim date);
    
CREATE TABLE Artigo (
	ID_Artigo integer PRIMARY KEY,
	ID_Proj integer,
	Titulo varchar(50),
	Resumo varchar(2500),
	DOI varchar(50),
	Link varchar(100),
	Dt_Pub date,
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj));

CREATE TABLE Funcionario (
	ID_Func integer PRIMARY KEY,
	Nome varchar(50),
	CPF varchar(11),
	Cargo varchar(50));
    
CREATE TABLE Proj_Func (
	ID_Proj integer,
	ID_Func integer,
	PRIMARY KEY(ID_Proj, ID_Func),
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func));
    
CREATE TABLE Proj_Esp (
	ID_Proj integer,
	ID_Esp integer,
	PRIMARY KEY(ID_Proj,ID_Esp),
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp));

CREATE TABLE Categoria (
	ID_Categ integer PRIMARY KEY,
	Descritivo varchar(50));

CREATE TABLE Proj_Cat (
	ID_Proj integer,
	ID_Categ integer,
	PRIMARY KEY(ID_Proj,ID_Categ),
	FOREIGN KEY(ID_Categ) REFERENCES Categoria (ID_Categ));

CREATE TABLE Laboratorio (
	ID_Lab integer PRIMARY KEY,
	Nome varchar(50),
	Endereco varchar(100));

CREATE TABLE Contrato (
	ID_Contrato integer PRIMARY KEY,
	ID_Func integer,
	ID_Lab integer,
	Status varchar(50),
	Dt_Inicio date,
	Dt_Fim date,
	Valor decimal(10,2),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func),
	FOREIGN KEY(ID_Lab) REFERENCES Laboratorio (ID_Lab));

CREATE TABLE Financiador (
	ID_Financiador integer PRIMARY KEY,
	Descritivo varchar(50),
	Endereco varchar(100));

CREATE TABLE Financiamento (
	ID_Financiamento integer PRIMARY KEY,
	ID_Proj integer,
	ID_Financiador integer,
	Valor decimal(10,2),
	Dt_Financ date,
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Financiador) REFERENCES Financiador (ID_Financiador));

CREATE TABLE Equipamento (
	ID_Equip integer PRIMARY KEY,
	ID_Lab integer,
	Tipo varchar(50),
	Modelo varchar(50),
	FOREIGN KEY(ID_Lab) REFERENCES Laboratorio (ID_Lab));

CREATE TABLE Registro_de_Uso (
	ID_Func integer,
	ID_Equip integer,
	Dt_Reg timestamp,
	PRIMARY KEY(ID_Func,ID_Equip),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func),
	FOREIGN KEY(ID_Equip) REFERENCES Equipamento (ID_Equip));
```
