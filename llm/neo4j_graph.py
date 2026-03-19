# llm/neo4j_processor.py
from neo4j import GraphDatabase, exceptions
import warnings

warnings.filterwarnings("ignore")


class Neo4jKnowledgeGraph:
    """独立的Neo4j知识图谱处理器（完全解耦）"""

    def __init__(self, uri="bolt://localhost:7687", username="neo4j", password="你的密码"):
        self.uri = uri
        self.username = username
        self.password = password
        self.driver = None
        self._connect()

    def _connect(self):
        """建立Neo4j连接（内部方法）"""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password)
            )
            # 测试连接
            with self.driver.session() as session:
                session.run("RETURN 1")
            print("✅ Neo4j知识图谱连接成功")
        except exceptions.Neo4jError as e:
            print(f"❌ Neo4j连接失败: {e}")
            self.driver = None
        except Exception as e:
            print(f"❌ 未知错误: {e}")
            self.driver = None

    def close(self):
        """关闭连接（建议程序退出时调用）"""
        if self.driver:
            self.driver.close()
            print("✅ Neo4j连接已关闭")

    def extract_entity_relation(self, text, llm_client, max_relations=20):
        """
        从文本中提取实体关系（调用LLM，完全解耦）
        :param text: 待提取的文本
        :param llm_client: LLM客户端（仅传接口，不依赖具体实现）
        :param max_relations: 最大提取关系数
        :return: 实体关系列表
        """
        if not text or not llm_client:
            return []

        # 提取关系的提示词
        prompt = f"""
        从以下文本中提取**产品、参数、功能、操作建议、故障解决方案**类的实体关系，格式严格为：实体1-关系-实体2
        要求：
        1. 只提取有明确关联的关系，拒绝模糊表述
        2. 每条关系一行，不超过50字
        3. 最多提取{max_relations}条，重复的只保留一条
        4. 实体名称尽量简洁（如"MacBook Air M2"而非"苹果公司的MacBook Air M2笔记本电脑"）

        文本：
        {text[:5000]}  # 限制长度，避免LLM上下文超限
        """

        try:
            # 调用LLM提取关系
            result = llm_client.invoke(prompt)
            # 解析结果
            relations = [r.strip() for r in result.split("\n") if "-" in r and len(r.strip()) > 5]
            # 去重+限制数量
            unique_relations = list(set(relations))[:max_relations]
            return unique_relations
        except Exception as e:
            print(f"❌ 实体关系提取失败: {e}")
            return []

    def add_relations(self, relations):
        """
        批量添加实体关系到Neo4j
        :param relations: 关系列表，格式["实体1-关系-实体2", ...]
        :return: 成功添加的数量
        """
        if not self.driver or not relations:
            return 0

        success_count = 0
        with self.driver.session() as session:
            for relation in relations:
                try:
                    parts = relation.split("-")
                    if len(parts) != 3:
                        continue
                    entity1, rel, entity2 = parts[0].strip(), parts[1].strip(), parts[2].strip()

                    # Cypher：MERGE避免重复创建
                    cypher = """
                    MERGE (a:Entity {name: $entity1})
                    MERGE (b:Entity {name: $entity2})
                    MERGE (a)-[r:RELATION {name: $rel}]->(b)
                    RETURN a, b, r
                    """
                    session.run(
                        cypher,
                        entity1=entity1,
                        rel=rel,
                        entity2=entity2
                    )
                    success_count += 1
                except Exception as e:
                    print(f"⚠️ 跳过无效关系[{relation}]: {e}")
                    continue

        print(f"✅ Neo4j新增{success_count}条有效关系")
        return success_count

    def retrieve_relations(self, keywords, limit=10):
        """
        根据关键词检索关联关系
        :param keywords: 关键词列表（如["MacBook", "电池寿命"]）
        :param limit: 最大返回关系数
        :return: 关系列表
        """
        if not self.driver or not keywords:
            return []

        all_relations = []
        with self.driver.session() as session:
            for keyword in keywords[:3]:  # 最多取3个关键词，避免检索过慢
                cypher = """
                MATCH (a)-[r:RELATION]->(b)
                WHERE a.name CONTAINS $keyword OR b.name CONTAINS $keyword
                RETURN a.name as entity1, r.name as relation, b.name as entity2
                LIMIT $limit
                """
                try:
                    result = session.run(cypher, keyword=keyword, limit=limit)
                    for record in result:
                        rel_str = f"{record['entity1']}-{record['relation']}-{record['entity2']}"
                        all_relations.append(rel_str)
                except Exception as e:
                    print(f"⚠️ 关键词[{keyword}]检索失败: {e}")
                    continue

        # 去重+限制数量
        unique_relations = list(set(all_relations))[:limit]
        return unique_relations