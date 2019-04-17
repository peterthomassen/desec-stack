import desecapi.models
from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    replaces = [('desecapi', '0001_initial'), ('desecapi', '0002_donation'), ('desecapi', '0003_auto_20151008_1023'), ('desecapi', '0004_remove_donation_rip'), ('desecapi', '0005_auto_20151008_1042'), ('desecapi', '0006_auto_20151018_1234'), ('desecapi', '0007_domain_updated'), ('desecapi', '0008_django_update_1-10'), ('desecapi', '0009_auto_20161201_1548'), ('desecapi', '0010_auto_20161219_1242'), ('desecapi', '0011_user_limit_domains'), ('desecapi', '0012_move_dyn_flag'), ('desecapi', '0013_acme_challenge'), ('desecapi', '0014_ip_validation'), ('desecapi', '0015_rrset'), ('desecapi', '0016_dyn_flag_default'), ('desecapi', '0017_rr_model'), ('desecapi', '0018_prune_domain_fields'), ('desecapi', '0019_rrset_uuid'), ('desecapi', '0020_user_locked'), ('desecapi', '0021_tokens'), ('desecapi', '0022_domain_published')]

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(default=django.utils.timezone.now, blank=True, null=True, verbose_name='last login')),
                ('email', models.EmailField(max_length=191, unique=True, verbose_name='email address')),
                ('is_active', models.BooleanField(default=True)),
                ('is_admin', models.BooleanField(default=False)),
                ('registration_remote_ip', models.CharField(blank=True, max_length=1024)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('limit_domains', models.IntegerField(blank=True, default=5, null=True)),
                ('dyn', models.BooleanField(default=False)),
                ('locked', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='Donation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(default=desecapi.models.get_default_value_created)),
                ('name', models.CharField(max_length=255)),
                ('iban', models.CharField(max_length=34)),
                ('bic', models.CharField(max_length=11)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=8)),
                ('message', models.CharField(blank=True, max_length=255)),
                ('due', models.DateTimeField(default=desecapi.models.get_default_value_due)),
                ('mref', models.CharField(default=desecapi.models.get_default_value_mref, max_length=32, blank=True)),
                ('email', models.EmailField(blank=True, max_length=255)),
            ],
            options={
                'ordering': ('created',),
            },
        ),
        migrations.CreateModel(
            name='Domain',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('name', models.CharField(max_length=191, unique=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='domains', to=settings.AUTH_USER_MODEL)),
                ('published', models.DateTimeField(null=True)),
            ],
            options={
                'ordering': ('created',),
            },
        ),
        migrations.CreateModel(
            name='RRset',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(null=True)),
                ('subname', models.CharField(blank=True, max_length=178)),
                ('type', models.CharField(max_length=10, validators=[desecapi.models.validate_upper])),
                ('ttl', models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('domain', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rrsets', to='desecapi.Domain')),
            ],
            options={
                'unique_together': {('domain', 'subname', 'type')},
            },
        ),
        migrations.CreateModel(
            name='RR',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('content', models.CharField(max_length=4092)),
                ('rrset', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='records', to='desecapi.RRset')),
            ],
        ),
        migrations.CreateModel(
            name='Token',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, verbose_name='Created')),
                ('key', models.CharField(db_index=True, max_length=40, unique=True, verbose_name='Key')),
                ('name', models.CharField(default='', max_length=64, verbose_name='Name')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='auth_tokens', to=settings.AUTH_USER_MODEL, verbose_name='User')),
                ('user_specific_id', models.BigIntegerField(verbose_name='User-Specific ID')),
            ],
            options={
                'unique_together': {('user', 'user_specific_id')},
            },
        ),
    ]
