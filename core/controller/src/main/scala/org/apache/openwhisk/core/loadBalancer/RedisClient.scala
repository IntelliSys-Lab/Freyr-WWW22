/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.openwhisk.core.loadBalancer

import org.apache.commons.pool2.impl.GenericObjectPoolConfig
import redis.clients.jedis. JedisPool


class RedisClient(
  host: String = "172.31.14.27", 
  port: Int = 6379, 
  password: String = "openwhisk", 
  database: Int = 0
) {
  private var pool: JedisPool = _
  val interval: Int = 100 //ms

  def init: Unit = {
    val maxTotal: Int = 300
    val maxIdle: Int = 100
    val minIdle: Int = 1
    val timeout: Int = 30000

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

  //
  // Send observations to Redis
  //

  def setActivations(activations: Int): Boolean = {
    try {
      val jedis = pool.getResource
      val key: String = "n_undone_request"
      val value: String = activations.toString
      jedis.set(key, value)
      jedis.close()
      true
    } catch {
      case e: Exception => {
        false
      }
    }
  }

  def setAvailableCpu(permits: Int): Boolean = {
    try {
      val jedis = pool.getResource
      val key: String = "available_cpu"
      val value: String = permits.toString
      jedis.set(key, value)
      jedis.close()
      true
    } catch {
      case e: Exception => {
        false
      }
    }
  }

  def setAvailableMemory(permits: Int): Boolean = {
    try {
      val jedis = pool.getResource
      val key: String = "available_memory"
      val value: String = permits.toString
      jedis.set(key, value)
      jedis.close()
      true
    } catch {
      case e: Exception => {
        false
      }
    }
  }

  def setActivationsForInvoker(invoker: String, activations: Int): Boolean = {
    try {
      val jedis = pool.getResource
      val name: String = invoker
      val key: String = "n_undone_request"
      val value: String = activations.toString
      jedis.hset(name, key, value)
      jedis.close()
      true
    } catch {
      case e: Exception => {
        false
      }
    }
  }

  def setAvailableMemoryForInvoker(invokerList: IndexedSeq[String], memoryPermitsList: IndexedSeq[Int]): Boolean = {
    try {
      val jedis = pool.getResource
      val pipeline = jedis.pipelined()
      val numInovkers: Int = invokerList.size
      for (i <- 0 until numInovkers) {
        val name: String = invokerList(i)
        val key: String = "available_memory"
        val value: String = memoryPermitsList(i).toString
        pipeline.hset(name, key, value)
      }
      pipeline.sync()
      jedis.close()
      true
    } catch {
      case e: Exception => {
        false
      }
    }
  }
}
