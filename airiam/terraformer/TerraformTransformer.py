import os
import shutil


current_dir = os.path.abspath(os.path.dirname(__file__))
boilerplate_files = ["admins.tf", "developers.tf", "power_users.tf"]


class TerraformTransformer:
    def __init__(self, logger, profile):
        self.logger = logger
        self.profile = profile

    def transform(self, results):
        if not os.path.exists('terraform'):
            os.mkdir('terraform')
        with open('terraform/main.tf', 'w') as main_file:
            profile_str = ""
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
            users_and_groups = results['Rightsizing']['UserOrganization']
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

        os.system("terraform fmt -recursive")
        return {"Success": True}
