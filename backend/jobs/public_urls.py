from django.urls import path

from jobs.public_views import PublicIssueFacetsView, PublicIssueViewSet

public_issue_list = PublicIssueViewSet.as_view({'get': 'list'})
public_issue_detail = PublicIssueViewSet.as_view({'get': 'retrieve'})
public_issue_facets = PublicIssueFacetsView.as_view({'get': 'list'})

urlpatterns = [
    path('issues/', public_issue_list, name='public-issue-list'),
    path('issues/facets/', public_issue_facets, name='public-issue-facets'),
    path('issues/<int:reference>/', public_issue_detail, name='public-issue-detail'),
]
