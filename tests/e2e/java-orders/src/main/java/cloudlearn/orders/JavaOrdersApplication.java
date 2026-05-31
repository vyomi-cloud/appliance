package cloudlearn.orders;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

/**
 * Boot entry point. DataSourceAutoConfiguration is disabled because we build
 * the DataSource manually in {@link DataConfig} after fetching the DB password
 * from Secrets Manager at startup.
 */
@SpringBootApplication(exclude = {DataSourceAutoConfiguration.class})
public class JavaOrdersApplication {
    public static void main(String[] args) {
        SpringApplication.run(JavaOrdersApplication.class, args);
    }
}
