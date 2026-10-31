-- resource_rate_windows has one mutable 60-second window per scope.
DROP INDEX IF EXISTS resource_rate_scope;
ALTER TABLE resource_rate_windows DROP CONSTRAINT resource_rate_windows_pkey;
ALTER TABLE resource_rate_windows ADD PRIMARY KEY (scope);
