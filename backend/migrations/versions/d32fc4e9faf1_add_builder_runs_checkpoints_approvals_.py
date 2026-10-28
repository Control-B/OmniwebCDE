"""add builder runs checkpoints approvals deployments

Revision ID: d32fc4e9faf1
Revises: b08e748d1ace
Create Date: 2026-10-28 12:39:19.844673
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd32fc4e9faf1'
down_revision: str | None = 'b08e748d1ace'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('generation_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('instruction', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('stage', sa.String(length=32), nullable=False),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('steps', sa.JSON(), nullable=False),
    sa.Column('cost_usd', sa.Float(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('checkpoint_sha', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generation_runs_organization_id'), 'generation_runs', ['organization_id'], unique=False)
    op.create_index(op.f('ix_generation_runs_project_id'), 'generation_runs', ['project_id'], unique=False)
    op.create_index(op.f('ix_generation_runs_status'), 'generation_runs', ['status'], unique=False)
    op.create_table('approvals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.String(length=300), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('estimated_monthly_usd', sa.Float(), nullable=True),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('requested_by', sa.String(length=64), nullable=False),
    sa.Column('decided_by', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['generation_runs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_approvals_organization_id'), 'approvals', ['organization_id'], unique=False)
    op.create_index(op.f('ix_approvals_project_id'), 'approvals', ['project_id'], unique=False)
    op.create_index(op.f('ix_approvals_status'), 'approvals', ['status'], unique=False)
    op.create_table('checkpoints',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('sha', sa.String(length=40), nullable=False),
    sa.Column('parent_sha', sa.String(length=40), nullable=True),
    sa.Column('message', sa.String(length=300), nullable=False),
    sa.Column('author', sa.String(length=16), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('restores_sha', sa.String(length=40), nullable=True),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('undo_of', sa.String(length=40), nullable=True),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.Column('spec', sa.JSON(), nullable=True),
    sa.Column('migrations', sa.JSON(), nullable=False, server_default='[]'),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['generation_runs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'sha')
    )
    op.create_index(op.f('ix_checkpoints_created_at'), 'checkpoints', ['created_at'], unique=False)
    op.create_index(op.f('ix_checkpoints_project_id'), 'checkpoints', ['project_id'], unique=False)
    op.create_table('deployments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('environment', sa.String(length=16), nullable=False),
    sa.Column('cloud_connection_id', sa.Uuid(), nullable=False),
    sa.Column('commit_sha', sa.String(length=40), nullable=False),
    sa.Column('region', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('approval_id', sa.Uuid(), nullable=True),
    sa.Column('external_app_id', sa.String(length=100), nullable=True),
    sa.Column('external_deployment_id', sa.String(length=100), nullable=True),
    sa.Column('url', sa.String(length=300), nullable=True),
    sa.Column('estimated_monthly_usd', sa.Float(), nullable=False),
    sa.Column('rollback_of', sa.Uuid(), nullable=True),
    sa.Column('app_spec', sa.JSON(), nullable=False),
    sa.Column('log', sa.JSON(), nullable=False),
    sa.Column('requested_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['approval_id'], ['approvals.id'], ),
    sa.ForeignKeyConstraint(['cloud_connection_id'], ['cloud_connections.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['rollback_of'], ['deployments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deployments_organization_id'), 'deployments', ['organization_id'], unique=False)
    op.create_index(op.f('ix_deployments_project_id'), 'deployments', ['project_id'], unique=False)
    op.add_column('projects', sa.Column('spec', sa.JSON(), nullable=True))
    op.add_column('projects', sa.Column('migrations', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('projects', sa.Column('head_sha', sa.String(length=40), nullable=True))
    op.add_column('projects', sa.Column('preview_token', sa.String(length=64), nullable=True))
    op.add_column('projects', sa.Column('last_build', sa.JSON(), nullable=True))
    op.add_column('projects', sa.Column('github_installation_id', sa.String(length=40), nullable=True))
    op.add_column('projects', sa.Column('github_default_branch', sa.String(length=100), nullable=False, server_default='main'))
    op.add_column('projects', sa.Column('last_pushed_sha', sa.String(length=40), nullable=True))
    op.add_column('projects', sa.Column('last_pulled_sha', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_projects_preview_token'), 'projects', ['preview_token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_projects_preview_token'), table_name='projects')
    op.drop_column('projects', 'last_pulled_sha')
    op.drop_column('projects', 'last_pushed_sha')
    op.drop_column('projects', 'github_default_branch')
    op.drop_column('projects', 'github_installation_id')
    op.drop_column('projects', 'last_build')
    op.drop_column('projects', 'preview_token')
    op.drop_column('projects', 'head_sha')
    op.drop_column('projects', 'migrations')
    op.drop_column('projects', 'spec')
    op.drop_index(op.f('ix_deployments_project_id'), table_name='deployments')
    op.drop_index(op.f('ix_deployments_organization_id'), table_name='deployments')
    op.drop_table('deployments')
    op.drop_index(op.f('ix_checkpoints_project_id'), table_name='checkpoints')
    op.drop_index(op.f('ix_checkpoints_created_at'), table_name='checkpoints')
    op.drop_table('checkpoints')
    op.drop_index(op.f('ix_approvals_status'), table_name='approvals')
    op.drop_index(op.f('ix_approvals_project_id'), table_name='approvals')
    op.drop_index(op.f('ix_approvals_organization_id'), table_name='approvals')
    op.drop_table('approvals')
    op.drop_index(op.f('ix_generation_runs_status'), table_name='generation_runs')
    op.drop_index(op.f('ix_generation_runs_project_id'), table_name='generation_runs')
    op.drop_index(op.f('ix_generation_runs_organization_id'), table_name='generation_runs')
    op.drop_table('generation_runs')
