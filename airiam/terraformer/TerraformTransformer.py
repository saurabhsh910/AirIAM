import json
import os
import shutil

import terrascript
import terrascript.resource as resource
import terrascript.data as data

from airiam.models.RuntimeReport import RuntimeReport

current_dir = os.path.abspath(os.path.dirname(__file__))
boilerplate_files = ["admins.tf", "developers.tf", "power_users.tf"]


class TerraformTransformer:
    def __init__(self, logger, profile=None):
        self.logger = logger
        self.profile = profile

    def transform(self, results):
        """
        Creates terraform files from the setup it receives
        :param results: IAM scan results
        :type results: RuntimeReport
        :return:
        """
        if not os.path.exists('terraform'):
            os.mkdir('terraform')
        if not os.path.exists('terraform/backup'):
            os.mkdir('terraform/backup')

        self.create_backup_code(results.raw_results)

        with open('terraform/main.tf', 'w') as main_file:
            if self.profile:
                profile_str = f"profile = \"{self.profile}\""
                main_file.write(f"""provider "aws" {{
  region  = "us-east-1"
  {profile_str}
}}
""")
            else:
                main_file.write(f"""provider "aws" {{
  region = "us-east-1"
}}
""")

            users_and_groups = results.get_rightsizing()['Users']
            powerusers_users = users_and_groups['Powerusers']['Users']
            powerusers_policies = users_and_groups['Powerusers']['Policies']
            main_file.write(f"""
locals {{
    admin_users = ["{'", "'.join(users_and_groups["Admins"])}"]
    developer_users = ["{'", "'.join(users_and_groups["ReadOnly"])}"]
    power_users = ["{'", "'.join(powerusers_users)}"]
    power_users_policy_arns = ["{'", "'.join(powerusers_policies)}"]
}}
""")
        for boilerplate_file in boilerplate_files:
            shutil.copyfile(current_dir + "/tf_modules/users/" + boilerplate_file, 'terraform/' + boilerplate_file)

        roles_str = ""
        for role in results.get_rightsizing()['Roles']:
            role_name_safe = TerraformTransformer.get_safe_entity_name(role['Entity']['RoleName'])
            assume_policy_data = self.transform_document_to_policy(role['Entity']['AssumeRolePolicyDocument'], f"assume_role_{role_name_safe}")
            role_obj = self.create_role_obj(role['Entity'], role_name_safe)
            policy_attachments = TerraformTransformer.create_role_policy_attachments(role['Entity'].get('AttachedManagedPolicies', []), role_name_safe)
            policy_documents = self.create_role_policy_documents(role['Entity'].get('RolePolicyList', []), role_name_safe)
            roles_str += "\n".join([assume_policy_data, role_obj, policy_attachments, policy_documents])

        with open("terraform/roles.tf", "w") as roles_file:
            roles_file.write(roles_str)
        os.system("terraform fmt -recursive")
        return {"Success": True}

    def transform_document_to_policy(self, policy, policy_name):
        if 'Principal' in policy['Statement'][0]:
            statements = self.transform_assume_policy_statements(policy['Statement'])
        else:
            statements = self.transform_execution_policy(policy['Statement'])

        policy_data_obj = f"""
data "aws_iam_policy_document" "{policy_name}" {{
  version = "{policy['Version']}"
{statements}
}}"""
        return policy_data_obj

    @staticmethod
    def transform_execution_policy(statements):
        statement_block = ""
        for statement in statements:
            sid_string = ""
            if 'Sid' in statement:
                sid_string = f"""  sid    = "{statement['Sid']}"
"""
            statement_block += f"""  statement {{
  {sid_string}effect = "{statement['Effect']}"
  action = {json.dumps(statement['Action'])}
}}
"""

        return statement_block

    @staticmethod
    def transform_assume_policy_statements(statements):
        statement_block = ""
        for statement in statements:
            statement_block += f"""  statement {{
    effect = "{statement['Effect']}"
    action = "{statement['Action']}"
    principals {{
      type        = "{list(statement['Principal'].keys())[0]}"
      identifiers = {json.dumps(list(statement['Principal'].values()))}
    }} 
  }}
"""

        return statement_block

    @staticmethod
    def create_role_obj(role, role_name_safe):
        result = f"""
resource "aws_iam_role" "{role_name_safe}" {{
  name               = "{role['RoleName']}"
  path               = "{role['Path']}"
  assume_role_policy = data.aws_iam_policy_document.assume_role_{role_name_safe}
}}
"""
        return result

    @staticmethod
    def create_role_policy_attachments(role_policy_attachments, role_name_safe):
        attachments = ""
        for attachment in role_policy_attachments:
            policy_name = attachment['PolicyName']
            attachments += f"""
resource "aws_iam_role_policy_attachment" "attachment_{role_name_safe}_{policy_name}" {{
  role       = aws_iam_role.{role_name_safe}.name
  policy_arn = "{attachment['PolicyArn']}"
}}
"""
        return attachments

    def create_role_policy_documents(self, role_policies, role_name_safe):
        policies = ""
        for role_policy in role_policies:
            role_policy_name = role_policy['PolicyName']
            document_str = self.transform_document_to_policy(role_policy['PolicyDocument'], role_policy_name)
            policy_str = f"""
{document_str}

resource "aws_iam_role_policy" "{role_name_safe}_{role_policy_name}" {{
  role   = aws_iam_role.{role_name_safe}.name
  policy = data.aws_iam_policy_document.{role_policy_name}.json
}}
"""
            policies += policy_str
        return policies

    def create_backup_code(self, current_iam_entities):
        terraform_code = terrascript.Terrascript()

        for policy in current_iam_entities['AccountPolicies']:
            policy_name = TerraformTransformer.get_safe_entity_name(policy['PolicyName'])
            policy_document = data.aws_iam_policy_document(f"{policy_name}_document", statement={"effect": "Allow"})
            terraform_code += policy_document
            terraform_code += resource.aws_iam_policy(policy_name, name=policy['PolicyName'], policy=policy_document)

            # print(policy)
            # todo: create policies

        # for role in current_iam_entities['AccountRoles']:
            # print(role)
            # todo: create roles and attach policies to them

        # for group in current_iam_entities['AccountGroups']:
            # print(group)
            # todo: create groups

        # for user in current_iam_entities['AccountUsers']:
            # print(user)
            # todo: attach policies to existing users

        # print(current_iam_entities)

    @staticmethod
    def convert_policy_json_to_terraform(policy_json, policy_safe_name):
        policy_document_json = next(x for x in policy_json['PolicyVersionList'] if x['IsDefaultVersion'])
        policy = TerraformTransformer.transform_document_to_policy()
        return f"""
resource "aws_iam_policy" "{policy_safe_name}" {{
  name = {policy_json['PolicyName']}
  path = {policy_json['Path']}
}}
"""

    @staticmethod
    def get_safe_entity_name(entity_raw_name):
        return ''.join(e for e in entity_raw_name if e.isalnum() or e == '_' or e == '-')
