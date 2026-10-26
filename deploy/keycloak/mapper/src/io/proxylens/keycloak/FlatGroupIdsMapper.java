package io.proxylens.keycloak;

import java.util.List;
import org.keycloak.models.GroupModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.ClientSessionContext;
import org.keycloak.models.ProtocolMapperModel;
import org.keycloak.models.UserSessionModel;
import org.keycloak.protocol.oidc.mappers.AbstractOIDCProtocolMapper;
import org.keycloak.protocol.oidc.mappers.OIDCAccessTokenMapper;
import org.keycloak.provider.ProviderConfigProperty;
import org.keycloak.representations.IDToken;

/** Keycloak 26.8.1 only. Claims come from models, never editable user attributes. */
public final class FlatGroupIdsMapper extends AbstractOIDCProtocolMapper
        implements OIDCAccessTokenMapper {
    @Override public String getId() { return "proxylens-flat-group-ids"; }
    @Override public String getDisplayType() { return "ProxyLens flat group IDs"; }
    @Override public String getDisplayCategory() { return TOKEN_MAPPER_CATEGORY; }
    @Override public String getHelpText() { return "Stable IDs; rejects hierarchical membership."; }
    @Override public List<ProviderConfigProperty> getConfigProperties() { return List.of(); }

    @Override
    protected void setClaim(IDToken token, ProtocolMapperModel model, UserSessionModel session,
            KeycloakSession keycloakSession, ClientSessionContext clientSession) {
        try (var stream = session.getUser().getGroupsStream()) {
            var groups = stream.limit(257).toList();
            boolean flat = groups.size() <= 256;
            for (var group : groups) {
                try (var children = group.getSubGroupsStream()) {
                    if (group.getParentId() != null || children.findAny().isPresent()) {
                        flat = false;
                    }
                }
            }
            token.getOtherClaims().put("proxylens_groups_flat", flat);
            token.getOtherClaims().put("proxylens_group_ids", flat
                    ? groups.stream().map(GroupModel::getId).distinct().sorted().toList()
                    : List.of());
        }
    }
}
