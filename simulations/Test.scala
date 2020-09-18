import org.apache.commons.pool2.impl.GenericObjectPoolConfig
import redis.clients.jedis.{Jedis, JedisPool, Response}
import redis.clients.util.Pool

class RedisClient(
  host: String, 
  port: Int, 
  password: String, 
  database: Int = 0
) {
  private val maxTotal = 300
  private val maxIdle = 100
  private val minIdle = 1
  private val timeout: Int = 30000 // ms

  private var pool: Pool[Jedis] = _

  def init: Unit = {
    val poolConfig = new GenericObjectPoolConfig()
    poolConfig.setMaxTotal(maxTotal)
    poolConfig.setMaxIdle(maxIdle)
    poolConfig.setMinIdle(minIdle)

    pool = new JedisPool(poolConfig, host, port, timeout, password, database)
  }

  def getPool: JedisPool = {
    assert(pool != null)
    pool
  }

  def setAvailableMemory(invoker: String, memoryPermits: Int): Boolean = {
    try {
      val jedis = pool.getResource
      val key: String = "available_memory"
      jedis.hset(invoker, key, memoryPermits)
      jedis.close()
      true
    } catch {
      case e: Exception => {
        false
      }
    }
  }

  def setAvailableCpu(invoker: String, cpuPermits: Int): Boolean = {
    try {
      val jedis = pool.getResource
      val key: String = "available_cpu"
      jedis.hset(invoker, key, cpuPermits)
      jedis.close()
      true
    } catch {
      case e: Exception => {
        false
      }
    }
  }

  def setUndoneRequestNumber(undoneRequestNum: Int): Boolean = {
    try {
      val jedis = pool.getResource
      val key: String = "n_undone_request"
      jedis.set(key, undoneRequestNum)
      jedis.close()
      true
    } catch {
      case e: Exception => {
        false
      }
    }
  }
}

object RedisClient {
  def main(args: Array[String]) {
    val redisHost: String = "192.168.196.213"
    val redisPort: Int = 6379
    val redisPassword: String = "openwhisk"

    val client = new RedisClient(redisHost, redisPort, redisPassword)
    client.setAvailableMemory("invoker0", 256)
  }
}