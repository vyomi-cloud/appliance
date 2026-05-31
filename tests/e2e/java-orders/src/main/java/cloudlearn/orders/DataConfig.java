package cloudlearn.orders;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import software.amazon.awssdk.services.secretsmanager.model.GetSecretValueRequest;

import javax.sql.DataSource;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Builds the Postgres DataSource AFTER fetching the secret from Secrets Manager.
 * The secret payload is expected to be a JSON object:
 *
 *   {"url":"jdbc:postgresql://host:5432/db","user":"admin","password":"..."}
 *
 * Demonstrates the standard pattern: app boots, reads secret, connects to RDS.
 */
@Configuration
public class DataConfig {

    private static final Logger log = LoggerFactory.getLogger(DataConfig.class);

    @Value("${cloudlearn.secret-name}")
    private String secretName;

    @Bean
    public DataSource dataSource(SecretsManagerClient sm) throws Exception {
        log.info("Fetching DB credentials from Secrets Manager: {}", secretName);
        String json = sm.getSecretValue(GetSecretValueRequest.builder()
                .secretId(secretName).build()).secretString();
        Map<String, String> creds = new ObjectMapper().readValue(json, Map.class);
        HikariConfig cfg = new HikariConfig();
        cfg.setJdbcUrl(creds.get("url"));
        cfg.setUsername(creds.get("user"));
        cfg.setPassword(creds.get("password"));
        cfg.setMaximumPoolSize(5);
        cfg.setConnectionTimeout(5000);
        DataSource ds = new HikariDataSource(cfg);
        // Bootstrap schema — idempotent CREATE TABLE.
        try (var c = ds.getConnection();
             var st = c.createStatement()) {
            st.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id          SERIAL PRIMARY KEY,
                    customer    TEXT NOT NULL,
                    total_cents BIGINT NOT NULL,
                    cc_enc      TEXT,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
                """);
        }
        log.info("Connected to Postgres + ensured schema");
        return ds;
    }

    @Bean
    public JdbcTemplate jdbcTemplate(DataSource ds) {
        return new JdbcTemplate(ds);
    }
}
